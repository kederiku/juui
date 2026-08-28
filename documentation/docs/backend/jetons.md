---
title: Jetons d'authentification
description: "Le port TokenService et son adaptateur PyJWT : neuf claims, une audience par application, un groupe actif vérifié à l'émission."
---

# Jetons d'authentification

Un jeton dit **qui tu es**, **pour quelle application**, et **chez qui tu travailles**. Cette page
décrit le contrat que le domaine connaît, l'adaptateur qui le tient, ce que ce dernier corrige aux
défauts de PyJWT, et les erreurs qu'un appelant doit savoir attraper.

Le domaine ne connaît que le port `TokenService`. PyJWT, l'algorithme, le secret, les durées et la
table des audiences vivent dans `shared/infrastructure/security/` : le contrat `domain-purity`
nomme `jwt` parmi les paquets interdits au domaine, et il refuse aussi les chaînes **indirectes** —
un port ne peut donc pas même importer `app.core`, qui importe pydantic. C'est cette contrainte, et
non un goût pour l'abstraction, qui explique la forme du port.

La décision d'ensemble est instruite dans
l'[ADR-0024](../adr/0024-jetons-audience-par-application.md).

## Les neuf claims

| Claim             | Type   | Ce qu'il dit                                                      |
| ----------------- | ------ | ----------------------------------------------------------------- |
| `sub`             | chaîne | Le compte authentifié — un UUID sérialisé.                        |
| `exp`             | entier | L'instant après lequel le jeton ne vaut plus rien.                |
| `iat`             | entier | L'instant de l'émission.                                          |
| `jti`             | chaîne | L'identifiant du jeton, sur lequel BACK-10d posera la révocation. |
| `type`            | chaîne | `access` ou `refresh` — les deux ne sont pas interchangeables.    |
| `aud`             | chaîne | L'application destinataire, et une seule.                         |
| `account_type`    | chaîne | `professional`, `individual` ou `admin`.                          |
| `active_group_id` | chaîne | Le groupe dans lequel le porteur travaille, ou `null`.            |
| `group_role`      | chaîne | Son rôle **de périmètre groupe** dans ce groupe, ou `null`.       |

Les deux derniers sont nuls ensemble ou renseignés ensemble : un compte particulier n'appartient à
aucun groupe, et c'est le cas nominal, pas une anomalie.

Ce que le jeton **ne porte pas** : les rôles de périmètre **clinique** (Vétérinaire, ASV). Ils se
résolvent à la requête, par le port d'affectation de BACK-16, parce qu'un vétérinaire change de
clinique dans la journée. Le jeton dit chez qui tu travailles, l'en-tête `X-Clinic-Id` dit où —
[ADR-0012](../adr/0012-perimetre-de-requete.md).

## Le port, et ce qu'il promet

Trois opérations asynchrones : `create_access_token`, `create_refresh_token`, `decode_token`. Trois
règles les accompagnent, écrites dans la docstring de `TokenService` parce que tout le reste en
dépend.

**1. Aucune opération ne dégrade.** C'est la réponse que donnent aussi `FileStorage`,
`EmailTransport` et `PasswordHasher` — l'unité de travail allant plus loin encore, puisqu'elle
lève **et annule**. Ici, le motif est le plus simple de tous : un jeton émis alors que
l'appartenance n'a pas pu être vérifiée est une élévation de privilège qui vivra jusqu'à son
expiration, sans que personne apprenne qu'elle a eu lieu. Un dépôt injoignable, une horloge mal injectée, une clé trop courte : rien de tout cela ne
produit un jeton par défaut.

**2. Le rôle vient du dépôt, jamais de l'appelant.** `group_role` ne figure dans aucune signature
d'émission. Un cas d'usage ne peut donc pas se déclarer gérant — il n'a pas de paramètre pour le
faire. C'est la différence entre une règle écrite dans une docstring et une règle que la signature
rend **inexprimable**.

**3. Les claims d'un jeton de rafraîchissement ne font pas autorité.** Ils disent ce qui était vrai
il y a jusqu'à sept jours. Tout renouvellement repasse par `create_access_token`, donc par la
vérification d'appartenance.

## L'audience : ce qui sépare vraiment les trois applications

Trois interfaces étanches servies par une seule API. Inscrire le type de compte dans le jeton et le
lire à chaque route ne suffit pas : un jeton de compte particulier, parfaitement signé et non
expiré, **reste techniquement présentable** à l'API professionnelle. Rien dans le jeton ne l'en
empêche.

Chaque application a donc son audience — `JWT_AUDIENCE_PROFESSIONAL`, `JWT_AUDIENCE_INDIVIDUAL`,
`JWT_AUDIENCE_ADMIN` — et `decode_token` **exige** l'audience attendue en argument obligatoire. Il
n'existe aucun moyen de décoder sans regarder l'audience.

La configuration refuse deux audiences identiques. Ce n'est pas de la coquetterie : deux valeurs
égales fondent deux applications en une, et rien nulle part ne lève — l'isolation disparaît en
silence.

L'audience reste un **paramètre** d'émission : la règle « un particulier n'obtient jamais un jeton
d'audience professionnelle » est une règle de parcours de connexion, et elle appartient à BACK-29.
Ce ticket-là lira `audience_for(account_type)` plutôt que de recopier la table.

## Le groupe actif est vérifié, pas déclaré

`active_group_id` est un argument — l'appelant dit dans quel groupe il veut travailler — mais il
n'est pas déclaratif. À l'émission, le service interroge le dépôt d'appartenances de BACK-16 :

- appartenance active → le rôle qu'elle porte entre dans le jeton ;
- appartenance close, à venir, ou groupe auquel le compte n'a jamais appartenu → `InactiveMembershipError`,
  et **aucun jeton**. Les trois cas donnent le même message : les distinguer dirait au demandeur si
  le groupe existe.

**Un seul instant est figé pour toute l'émission.** Le même alimente `iat`, `exp` et la date à
laquelle l'appartenance est jugée active — deux appels à l'horloge produiraient un jeton affirmant
qu'une appartenance était active à un instant qui n'est pas celui qu'il porte.

Le rôle est ensuite figé pour la durée du jeton. Une rétrogradation met donc au plus une durée
d'access token — quinze minutes par défaut — à produire son effet ; l'urgence est couverte par la
révocation de BACK-10d.

## Ce que l'adaptateur corrige aux défauts de PyJWT

Cinq comportements par défaut, **mesurés et non lus**, qu'aucune règle métier ne rattrape :

| Défaut par défaut                                                                                                    | Ce que l'adaptateur impose                                                                                                               |
| -------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| Chaque contrôle est gardé par « si le claim est présent » : un jeton sans `exp` est accepté, et **n'expire jamais**. | Clause `require` sur les sept claims obligatoires.                                                                                       |
| Un `aud` sous forme de **liste** contenant l'audience attendue passe.                                                | `strict_aud`.                                                                                                                            |
| Une clé de cinq octets ne produit qu'un `warning`.                                                                   | `enforce_minimum_key_length`, plus une borne en configuration — indexée par l'algorithme (32 / 48 / 64 octets) et comptée en **octets**. |
| L'algorithme se lit dans l'en-tête du jeton.                                                                         | Liste **fermée**, dérivée du `Literal` de configuration.                                                                                 |
| Aucune tolérance d'horloge : cinq secondes de dérive suffisent à refuser un jeton valide.                            | Dix secondes de `leeway`.                                                                                                                |

Dix secondes, et pas davantage : ce que cette valeur absorbe, c'est la dérive entre deux instances
derrière un répartiteur — une seconde, pas dix minutes. Une tolérance large prolongerait exactement
ce qu'on cherche à borner.

## Les erreurs

Toutes descendent de `TokenError`, et **aucune exception de PyJWT n'en sort** : c'est la promesse
qui permet d'écrire `except TokenError` sans jamais importer la bibliothèque.

| Erreur                    | Quand                                                                                      |
| ------------------------- | ------------------------------------------------------------------------------------------ |
| `ExpiredTokenError`       | `exp` dépassé. La seule que le client a intérêt à distinguer : elle lui dit de rafraîchir. |
| `TokenNotYetValidError`   | `iat` dans le futur — une dérive d'horloge, pas un jeton illisible.                        |
| `InvalidSignatureError`   | Jeton forgé, ou clé changée depuis l'émission.                                             |
| `InvalidAudienceError`    | Le jeton vise une autre application — **ou n'en vise aucune**.                             |
| `WrongTokenTypeError`     | Un refresh présenté à une route métier, ou l'inverse.                                      |
| `MalformedTokenError`     | Illisible, incomplet, ou claim intypable.                                                  |
| `UnknownAudienceError`    | À l'émission : audience absente des trois déclarées.                                       |
| `UnknownAccountTypeError` | À l'émission : type de compte absent de la table des audiences.                            |
| `InactiveMembershipError` | À l'émission : aucune appartenance active à ce groupe.                                     |

Deux points méritent d'être connus.

**`InactiveMembershipError` hérite de deux familles** — `TokenError`, pour qu'un `except TokenError`
autour de l'émission ne la rate pas, et `NotFoundError`, pour la règle de non-divulgation de
[BACK-09](./erreurs.md) : un refus de droit confirmerait l'existence du groupe. Le traducteur
d'erreurs résolvant par `isinstance` sur un tuple ordonné où `NotFoundError` vient en tête, la
réponse est un **404**.

**Les autres n'ont pas de statut HTTP ici.** Le 401 d'authentification est posé à la bordure, par
`HTTPException` — c'est le chemin que BACK-09 a prévu, et son handler dédié préserve les en-têtes,
`WWW-Authenticate` compris. BACK-10a définit le vocabulaire ; [BACK-10c](./authentification.md), qui tient la
bordure, a tranché ce que le client en voit : **un seul 401, sans détail**, pour toutes les causes.
Des erreurs distinctes ne signifient pas des réponses bavardes.

Aucune erreur ne porte de `details` dérivé du jeton : le journal rédige les fragments sensibles, la
**réponse HTTP** non.

**Les pannes techniques ne sont pas des refus.** `TokenIssuanceError` et ses deux filles —
`NaiveInstantError`, `MembershipLookupFailedError` — vivent **hors** de la hiérarchie `DomainError`,
comme `EmailDeliveryError` : une base injoignable ou une horloge mal câblée sortent en 500 avec leur
trace, plutôt que de dire à l'appelant qu'il a fait quelque chose de travers. Le point commun avec un
refus reste entier : aucun jeton n'est émis.

Ce que la configuration écarte avant même que ces erreurs ne puissent se produire : une clé trop
courte pour l'algorithme retenu, une durée de vie assez grande pour faire déborder la date, une
audience vide ou bordée d'espaces. Chacune de ces trois valeurs laissait le service **démarrer** puis
échouer à chaque émission ; elles sont désormais refusées au démarrage, où le défaut se voit.

## Ce que ce ticket ne livre pas

Le **montage**, livré depuis par [BACK-10c](./authentification.md). Le service a besoin d'un
résolveur d'appartenance, qui a besoin de l'unité de travail d'`organization`, laquelle est une
dépendance de requête. Une dépendance FastAPI qui assemble les deux ne peut vivre ni dans `shared`,
qui n'a pas le droit d'importer un module, ni dans un module, qui n'a pas le droit d'en connaître un
autre : seul `main.py` le peut. C'est la réponse qu'a retenue BACK-10c — les dépendances vivent dans
`shared` et n'y connaissent que des **formes**, que le `lifespan` remplit.

Un test d'intégration branche par ailleurs le service sur le vrai dépôt et prouve que les deux
s'emboîtent.

## Vérifier que les règles tiennent

Même esprit que les sondes des autres pages. Depuis `backend/api/`, la pile Docker démarrée.

**La suite du ticket** — émission, décodage, refus, et le test d'intégration sur PostgreSQL :

```bash
uv run pytest -m tokens -v
```

**Le port reste pur** — attendu : `Contracts: 5 kept, 0 broken.`

```bash
make imports
```

**La configuration refuse ce qu'elle doit refuser** — deux audiences identiques, un algorithme
asymétrique, une clé trop courte :

```bash
uv run pytest tests/core/test_config_jwt.py -v
```
