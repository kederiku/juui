---
title: Erreurs à l'écran
description: "La table code → message de @repo/api-client, les trois replis, les deux règles de non-divulgation, les composants d'affichage et l'identifiant d'incident copiable."
---

# Erreurs à l'écran

Ce qu'un utilisateur lit quand l'API refuse — la table `code → message`, les trois replis, les deux
règles de vocabulaire qui ne se négocient pas, et le bloc d'erreur qui les rend.

Livré par FRONT-10, consigné dans
l'[ADR-0029](../adr/0029-message-choisi-par-le-client.md) : le serveur choisit le **code**, le
client choisit le **message**. `ApiError.message` — la phrase écrite au site de levée, sans accents,
pour un développeur — part au journal et ne s'affiche **jamais**.

| Chemin                                  | Ce qu'il porte                                                       |
| --------------------------------------- | -------------------------------------------------------------------- |
| `src/errors/api-error.ts`               | `ApiError`, la normalisation, le type dérivé du contrat.             |
| `src/errors/messages.ts`                | La table par module, les replis, `resolveApiError`, `toFieldErrors`. |
| `@repo/ui/components/error/error-state` | Le bloc d'alerte, purement présentationnel.                          |
| `@repo/ui/components/error/request-id`  | L'identifiant d'incident, copiable en un clic.                       |

## Traduire une erreur

Une seule fonction, et elle accepte **n'importe quoi** — c'est le point : un `catch` ne sait pas ce
qu'il attrape.

```tsx
'use client';

import { useCheckReadiness } from '@repo/api-client/api/health';
import { resolveApiError } from '@repo/api-client/errors/messages';
import { ErrorState } from '@repo/ui/components/error/error-state';
import { RequestId } from '@repo/ui/components/error/request-id';

export function ServiceStatus() {
  const { data, isPending, isError, error } = useCheckReadiness();

  if (isError) {
    const resolved = resolveApiError(error);
    return (
      <ErrorState message={resolved.message}>
        {resolved.visibleRequestId === null ? null : (
          <RequestId requestId={resolved.visibleRequestId} />
        )}
      </ErrorState>
    );
  }
  // …
}
```

`resolveApiError` rend six champs : `message` (jamais vide), `code`, `status`, `requestId`,
`isUnknownCode`, et `visibleRequestId`.

:::warning L'identifiant se pose HORS de l'alerte, et `ErrorState` s'en charge

`role="alert"` implique `aria-atomic="true"` : un lecteur d'écran relit **tout** le contenu de la
région à chaque changement. La confirmation « Identifiant copié » placée à l'intérieur ferait donc
réannoncer le message d'erreur entier à chaque clic, puis une seconde fois à sa disparition. C'est
pourquoi `ErrorState` rend ses `children` en **frère** de l'alerte et non en descendant — un appelant
qui envelopperait `RequestId` dans sa propre région `role="alert"` rouvrirait le problème.

:::

:::note `visibleRequestId` n'est pas `requestId`

`requestId` est ce qui **est arrivé** ; `visibleRequestId` est ce qu'il faut **afficher**, et il vaut
`null` dès qu'il n'y a rien d'utile à montrer — sur un 4xx, que l'utilisateur peut corriger seul, et
partout où l'identifiant est absent. Une première rédaction rendait un booléen à côté de la valeur :
chaque appelant devait alors recouper « faut-il l'afficher » avec « y en a-t-il un », et le premier
à l'oublier affichait un bloc vide.

:::

## La table, et ses trois replis

`messages.ts` porte **un enregistrement par module backend** — `shared`, `identity`, `organization`,
`scheduling`, `notifications`, `medical_records` — plus les erreurs de protocole et les quatre codes
fabriqués par le client lui-même, déclarés dans `CLIENT_ERROR_CODES` et tenus en regard de la table
par une sonde. Le découpage est celui du serveur, si bien qu'un code se cherche
là où on l'attend.

La résolution descend trois marches, dans cet ordre :

| Marche                   | Quand                   |
| ------------------------ | ----------------------- |
| La table                 | Le code y a une entrée. |
| Le message du **statut** | Le code n'y est pas.    |
| Le message générique     | Le statut non plus.     |

**Le repli par statut n'est pas décoratif.** Les erreurs de routage portent un code **dérivé** du
statut — `http.request.not_found`, `http.request.method_not_allowed`, un par entrée du registre
HTTP : les énumérer reviendrait à recopier la bibliothèque standard de Python, et le repli dit
exactement la même chose. C'est aussi lui qui tient la règle de vocabulaire sur un code que personne
n'a catalogué.

**Un code métier non traduit se journalise**, en nommant le code et le fichier où l'ajouter :

```
FRONT-10 : code d'erreur inconnu « identity.gadget.exploded » (statut 409). Ajouter son message a packages/api-client/src/errors/messages.ts.
```

Une seule fois par code, et non à chaque rendu : `resolveApiError` s'appelle dans le corps du rendu,
et l'avertissement se répéterait à l'identique — doublé sous `StrictMode`.

La famille dérivée `http.request.*` en est **exclue**, et c'est une correction mesurée à l'écran :
sans cette exception, chaque 404 ordinaire écrivait un avertissement, et celui qui compte — un code
métier oublié — s'y serait noyé.

## Les deux règles qui ne se négocient pas

**Une absence se dit « introuvable », jamais un refus de droit.** Le serveur répond 404 — et non
403 — pour une ressource appartenant à un autre groupe
([ADR-0014](../adr/0014-traduction-des-erreurs-a-la-bordure.md), qui porte la règle ;
[ADR-0013](../adr/0013-filtre-de-tenance-dans-le-depot.md) en donne le mécanisme côté dépôt) : un
refus d'accès confirmerait son existence chez un concurrent. Écrire « vous n'avez pas les droits » annulerait cette précaution
depuis l'interface. Une sonde refuse les mots « droit », « autorisation » et « permission » dans
tout message d'absence, repli 404 compris.

**L'inscription ne révèle jamais qu'une adresse est déjà utilisée.** Le refus est identique que
l'adresse soit libre ou prise, et le message de `identity.account.email_already_used` est figé au
mot près par une sonde. Le code, lui, reste lisible dans `ApiError.code` : c'est une donnée de
diagnostic, pas un texte affiché.

## L'identifiant d'incident

Le même identifiant est posé par l'API sur l'en-tête `X-Request-ID` et dans les lignes de journal
([Journalisation](../backend/journalisation.md)). C'est ce qui transforme « ça ne marche pas » en un
signalement retrouvable — d'où la copie en un clic, personne ne recopiant trente-deux caractères
hexadécimaux sans se tromper.

Il ne s'affiche que sur les **erreurs serveur** (5xx) et les absences de réponse, et seulement s'il
est arrivé.

:::warning Un vrai 500 arrive souvent sans identifiant

`ServerErrorMiddleware` répond hors de toute enveloppe de sortie, donc **sans en-têtes CORS** : le
navigateur présente la réponse au JavaScript comme un échec réseau, sans corps ni en-tête. Le cas
« pas d'identifiant à montrer » est donc le cas **courant** en navigateur, pas l'exception. L'écart
est consigné au [registre](../ecarts/back.md), côté BACK-11.

:::

Si le presse-papiers refuse — hors contexte sécurisé, ou document non focalisé —, l'échec est
**annoncé** et invite à sélectionner l'identifiant à la main. Le taire laisserait l'utilisateur
coller autre chose dans son signalement.

## Les erreurs de champ, sur un 422

`toFieldErrors` lit `details.errors` d'une réponse 422 et rend les messages **par champ**, dans la
forme qu'attend le `FieldError` de `@repo/ui` :

```ts
toFieldErrors(error);
// { email: [{ message: 'Ce champ est obligatoire.' }],
//   'pets.0.name': [{ message: 'Cette valeur est trop courte.' }] }
```

Le premier segment de `loc` nomme l'**emplacement** (`body`, `query`…) et non un champ : il est
retiré, le reste est joint par un point. Le message vient du `type` de violation Pydantic, **jamais**
de `msg` — qui est en anglais et vient du serveur.

Un 422 **métier** rend un objet vide, et c'est exact : une `ValidationError` du domaine porte un code
namespacé et des détails libres, sans pointeur de champ. L'appelant affiche alors le message au
niveau du formulaire, pas sur un champ deviné. Le câblage au patron de formulaire appartient à
FRONT-05.

## Vérifier

```bash
pnpm --filter @repo/api-client test
```

Dix contrôles **hors ligne**, sans pile démarrée, sans compilation et sans dépendance : le repli et
sa journalisation, l'invariance du message sur douze entrées pathologiques — clés d'`Object.prototype`
comprises —, le message du serveur qui ne ressort ni sur un code connu ni sur un code inconnu, le
vocabulaire du 404, la non-divulgation à l'inscription, la panne de configuration qui ne devient pas
« réessayez », l'identifiant qui ne s'annonce que quand il sert, le repositionnement par champ et ses
formes hostiles, la correspondance entre `CLIENT_ERROR_CODES` et la table, et l'absence de collision
entre les huit enregistrements.

C'est possible parce que `messages.ts` n'a **aucun import de valeur** : Node 24 efface les types à la
volée et exécute le fichier tel quel. **Cette pureté est porteuse** — la table et la résolution
vivent ensemble pour cette raison, un import relatif sans extension rendant le module inexécutable
par Node, et une auto-référence par la carte `exports` cassant la compilation `node10` de
`make verify-api-client`.

Le **rendu**, lui, n'est prouvé par aucun test tant que QA-02 n'a pas posé de runner. Il se regarde :

```bash
make dev
docker compose stop redis
```

`/health/ready` répond alors **503 par la route normale** — donc en traversant tous les intergiciels,
donc avec `X-Request-ID` exposé —, et la page de `frontend-professional` affiche le bloc complet,
identifiant copiable compris. Arrêter l'API entière ne le montrerait **pas** : la requête échouerait
au transport, sans réponse, donc sans identifiant.

:::note Ce que cette démonstration prouve, et ce qu'elle ne prouve pas

Le corps de ce 503 est un `ReadinessReport`, **pas** une erreur au format BACK-09 : la sonde répond
la même forme en panne et en santé, seul le code change. Le mutator ne peut donc pas y lire de code
métier et pose le sien, `api_client.response.malformed` — dont le message parle d'indisponibilité et
non de format, précisément parce que ce cas-là est le plus fréquent des trois qu'il couvre.

La démonstration prouve donc le **rendu** : le bloc, l'identifiant, la copie. Elle n'exerce aucune
entrée de la table par module — aucune route métier n'existe avant BACK-28, et un vrai 500 est
invisible au navigateur. Ces entrées-là sont couvertes par les sondes.

:::

:::note Une page en arrière-plan ne réessaie pas

En observant dans un navigateur piloté, l'écran peut rester sur « Hors ligne » : TanStack Query met
ses réessais en pause quand `document.visibilityState` vaut `hidden`, et un 5xx n'atteint alors
jamais son état d'erreur. Mettre l'onglet au premier plan suffit. Ce n'est pas un défaut du rendu
des erreurs — c'est la politique de réessai de
[Données côté client](./donnees-cote-client.md#ce-qui-se-réessaie-et-ce-qui-ne-se-réessaie-pas).

:::

## Ce qui viendra

- **FRONT-05** — le patron de formulaire, qui consommera `toFieldErrors`.
- **FRONT-18a** — les états de chargement et le réessai, et la frontière d'erreur que ce ticket a
  délibérément laissée de côté.
- **BACK-28** — les premières routes métier, donc les premiers codes réellement rendus à l'écran.

Les écarts assumés avec le ticket FRONT-10 sont consignés au
[registre des écarts](../ecarts/front.md#écarts-assumés-avec-le-ticket-front-10).
