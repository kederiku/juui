---
title: 'ADR-0029 — Le serveur choisit le code, le client choisit le message'
description: "Le texte d'erreur vu par un utilisateur est choisi côté client à partir du code namespacé de BACK-09 ; le `message` du serveur ne s'affiche jamais, et un code inconnu tombe sur un repli explicite plutôt que sur un écran vide."
---

# ADR-0029 — Le serveur choisit le code, le client choisit le message

| Statut      | Date       | Tickets                                                              |
| ----------- | ---------- | -------------------------------------------------------------------- |
| **Accepté** | 2026-08-28 | FRONT-10, FRONT-05 (à venir), FRONT-18a (à venir), BACK-28 (à venir) |

## Contexte

Décision rendue par FRONT-10, qui livre la première traduction d'erreurs côté client.

[BACK-09](../backend/erreurs.md) donne à chaque refus un **code namespacé** `<module>.<ressource>.<erreur>`
— porté en attribut de classe, donc aussi stable que le type — et un `message`. Ce message part dans
la réponse HTTP, et rien n'empêchait un écran de l'afficher tel quel. C'est même le geste le plus
court : le champ est là, il est en français, il décrit le refus.

Trois choses s'y opposent, et aucune ne se voit à la lecture d'une seule réponse.

La première est que **ce message est écrit pour un développeur**. « La requete ne respecte pas le
schema attendu. » est exact et inutilisable ; « Aucun compte ne porte l'identifiant demande. » parle
d'un identifiant que l'utilisateur n'a jamais vu. Ils sont écrits au site de levée, par la personne
qui code la règle, sans que personne ne relise l'ensemble.

La deuxième est qu'ils sont **sans accents** : le dépôt réserve les accents au Markdown et à ce qui
s'affiche ([Conventions du dépôt](../getting-started/conventions-du-depot.md)), et les messages
d'exception sont du code. Les afficher ferait sortir « Aucun compte ne porte l'identifiant demande »
à l'écran d'un cabinet.

La troisième est la plus sérieuse : **deux règles de non-divulgation du backend seraient annulées
par un affichage naïf**. Une ressource d'un autre groupe répond 404 et non 403
([ADR-0013](./0013-filtre-de-tenance-dans-le-depot.md)) ; dire « vous n'avez pas les droits »
rétablirait exactement l'oracle que ce choix évite. Et l'inscription répond la même chose qu'une
adresse soit libre ou prise ; ajouter « cet e-mail existe déjà » côté client, au nom du confort
d'usage, rouvrirait la même fuite. Ces deux règles vivent dans le serveur ; rien ne les tenait dans
l'interface.

## Décision

**Le serveur choisit le code, le client choisit le message.** `ApiError.message` — ce que le serveur
a écrit — est un message de **journal** : il part dans la console et dans les rapports d'incident, il
ne s'affiche jamais. Le texte vu par un utilisateur vient d'une table `code → message` qui vit côté
client, dans `packages/api-client/src/errors/messages.ts`, organisée par module backend.

**Un code non traduit tombe sur un repli explicite, jamais sur un écran vide.** Trois niveaux, dans
cet ordre : la table, puis un message par **statut HTTP**, puis un message générique. Le repli par
statut n'est pas un filet de secours décoratif — c'est lui qui couvre la famille `http.request.<statut>`,
dérivée du registre HTTP par les handlers de BACK-09 et donc non énumérable sans recopier la
bibliothèque standard de Python. C'est aussi lui qui tient la règle de vocabulaire sur un code que
personne n'a catalogué : le repli 404 dit « introuvable ».

**Un code métier non traduit se journalise.** Un `console.warn` nomme le code et le fichier où
l'ajouter. Sans lui, l'oubli est invisible : l'utilisateur voit une phrase générique parfaitement
crédible, et personne n'apprend qu'il manque une entrée. La famille dérivée `http.request.*` en est
exclue — mesuré à l'écran, chaque 404 ordinaire écrivait sinon un avertissement, et celui qui compte
s'y serait noyé.

**Les erreurs s'affichent là où la donnée était attendue.** `throwOnError` n'est pas posé : une
frontière d'erreur remplace la page entière, ce qui est le bon geste pour un écran cassé et jamais
pour un tableau qui n'a pas pu se charger. La frontière elle-même, avec le réessai, appartient à
FRONT-18a.

**Le type du corps d'erreur vient du contrat, pas d'une recopie.** `ApiErrorBody` est un alias du
`ErrorResponse` généré par Orval ([ADR-0007](./0007-client-api-genere-orval.md)). Pour cela, FRONT-10
a déclaré le 500 sur `/health/ready` côté serveur : la route le produisait déjà, seul le contrat se
taisait.

## Alternatives écartées

### Afficher le `message` du serveur

Le geste le plus court, et celui qu'on écrit sans y penser. Écarté pour les trois raisons du
contexte — registre de langue, accents, non-divulgation. La troisième suffirait seule : une règle de
sécurité tenue à un endroit et annulable à un autre n'est pas tenue.

### Traduire côté serveur, et n'envoyer qu'un texte prêt à afficher

Cohérent, et c'est ce que font beaucoup d'API. Écarté : le serveur devrait alors connaître la langue,
le canal et le contexte de l'appelant — trois applications, des courriels, une CLI —, et un même refus
ne se formule pas pareil dans un formulaire d'inscription et dans un journal d'exploitation. Le code
est le contrat ; le texte est de la présentation, et la présentation appartient au client.

### Une bibliothèque d'internationalisation

`next-intl` ou équivalent rangerait ces messages dans des catalogues par langue. Écarté **pour
l'instant** : le produit est monolingue, aucune bibliothèque d'i18n n'existe dans le dépôt, et
l'introduire ici trancherait à la place du ticket qui portera le sujet. La table est un objet
TypeScript ordinaire, indexé par code : la reprendre dans un catalogue le jour venu est une
transformation mécanique.

### Compléter la table depuis le backend, et échouer en intégration continue sur un code non traduit

Séduisant — un code neuf sans message deviendrait une erreur de CI. Écarté après mesure du câblage
réel : le workflow `api-client.yml` se déclenche sur `backend/**` **et** lance les sondes du client.
Une pull request purement backend qui ajoute un code deviendrait donc rouge, réparable seulement en
écrivant une phrase française dans un fichier frontend. C'est l'inverse de la frontière que ce
workflow existe pour tenir. Le repli explicite et sa journalisation **sont** la stratégie de
complétude.

### Un drapeau booléen pour décider d'afficher l'identifiant de requête

La première rédaction rendait `showsRequestId: boolean` à côté de `requestId: string | null`. Écarté
en revue : un vrai 500 ne traverse aucun intergiciel CORS (registre des écarts, BACK-11), le
navigateur le présente au JavaScript comme un échec réseau, et l'identifiant est perdu. Chaque
appelant aurait dû recouper « faut-il l'afficher » avec « y en a-t-il un », et le premier à l'oublier
aurait affiché un bloc vide. `visibleRequestId: string | null` rend l'état illégal irreprésentable.

## Conséquences

**Ce que cela donne.** Le texte vu par un vétérinaire se relit en un seul endroit, par module, sans
ouvrir le serveur. Les deux règles de non-divulgation sont tenues **des deux côtés**, et deux sondes
hors ligne les figent — l'une refuse tout vocabulaire de droit sur un message d'absence, l'autre fige
le refus d'inscription au mot près. Un code oublié se voit dans la console au lieu de se deviner.

**Ce que cela coûte.** Une table à tenir : cinquante-neuf entrées le jour de la décision, une de plus
à chaque code backend. Un décalage possible entre le serveur et le client, que rien ne rend
bloquant — c'est le prix assumé de l'alternative écartée ci-dessus. Et une duplication apparente
entre le message du serveur et celui du client, qui n'en est pas une : ils ne s'adressent pas aux
mêmes lecteurs.

**Ce que cela ne couvre pas.** Le repositionnement des messages sur les champs d'un formulaire est
livré comme adaptateur — il lit `details.errors` et rend la forme qu'attend `FieldError` — mais rien
ne l'exerce encore : aucune route n'accepte de corps avant BACK-28, et le patron de formulaire est
FRONT-05. Le rendu lui-même n'est prouvé par aucun test automatisé tant que QA-02 n'a pas posé de
runner ; il se vérifie à l'œil, et la page
[Erreurs à l'écran](../frontend/erreurs-a-l-ecran.md) dit comment.

## Références

- `packages/api-client/src/errors/messages.ts` — la table, les replis et la résolution.
- `packages/api-client/src/errors/api-error.ts` — la normalisation, et le type dérivé du contrat.
- `packages/api-client/scripts/verify-errors.ts` — les neuf sondes hors ligne.
- `packages/ui/src/components/error/` — l'affichage et l'identifiant copiable.
- [Erreurs à l'écran](../frontend/erreurs-a-l-ecran.md) — la page qui explique l'usage au quotidien.
- [ADR-0014](./0014-traduction-des-erreurs-a-la-bordure.md) — la décision jumelle, côté serveur :
  c'est elle qui porte la règle 404-jamais-403.
- [ADR-0007](./0007-client-api-genere-orval.md) — le contrat généré dont le type d'erreur dérive.
