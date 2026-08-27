---
title: ADR-0024 — Un jeton vise une seule application, et son groupe actif est vérifié à l'émission
description: L'isolation des trois interfaces tient à un claim `aud` vérifié au décodage, et le claim `active_group_id` est confronté au dépôt d'appartenances au moment où le jeton est signé.
---

# ADR-0024 — Un jeton vise une seule application, et son groupe actif est vérifié à l'émission

| Statut      | Date       | Tickets                                         |
| ----------- | ---------- | ----------------------------------------------- |
| **Accepté** | 2026-08-27 | BACK-10a, BACK-10c, BACK-10e, BACK-29 (à venir) |

## Contexte

Décision rendue par BACK-10a, qui livre la brique d'émission et de vérification des jetons derrière
le port `TokenService`.

Le cahier des charges demande **trois interfaces étanches** — professionnelle, particulier,
administration — servies par une seule API. Le réflexe est d'inscrire le type de compte dans le
jeton et de le lire à l'entrée de chaque route. Ce réflexe ne tient pas : un jeton de compte
particulier, **parfaitement signé et non expiré**, reste techniquement présentable à l'API
professionnelle. Rien dans le jeton ne l'en empêche ; seule une vérification applicative bien placée
le fait.

La seconde question est du même ordre. Le jeton porte `active_group_id` — le groupe dans lequel son
porteur travaille — et `group_role`, son rôle dans ce groupe. Ces deux claims décident du périmètre
de tenance de chaque requête ([ADR-0012](./0012-perimetre-de-requete.md)) et de l'autorisation par
rôle. Si l'appelant les fournit, il décide lui-même de ses propres droits.

Enfin, PyJWT a des **défauts permissifs** qu'aucun de ces raisonnements ne rattrape. Ils ont été
mesurés, pas lus : un jeton dépourvu d'`exp` est accepté et n'expire jamais ; un `aud` sous forme de
liste passe ; une clé de cinq octets ne produit qu'un avertissement.

## Décision

**Chaque application a son audience, et chaque décodage exige la sienne.** Trois variables
d'environnement (`JWT_AUDIENCE_PROFESSIONAL`, `JWT_AUDIENCE_INDIVIDUAL`, `JWT_AUDIENCE_ADMIN`), que
la configuration refuse de laisser identiques — deux audiences égales fondraient deux applications
en une sans qu'aucune erreur ne se produise nulle part. `decode_token` exige l'audience attendue en
argument obligatoire : il n'existe aucun moyen de décoder « sans regarder l'audience ».

**L'audience reste un paramètre d'émission, elle n'est pas déduite du type de compte.** La déduction
avait été envisagée, au motif que ce qui n'est pas passé ne peut pas être menti. L'argument
s'effondre : `account_type` vient du même appelant, et la déduction déplace le mensonge d'un
paramètre à l'autre au lieu de le supprimer. La règle « un particulier n'obtient jamais un jeton
d'audience professionnelle » est une règle de **parcours de connexion**, et elle appartient à
BACK-29 ; BACK-10a lui fournit la table par `audience_for(account_type)`, pour qu'elle ne soit
recopiée nulle part.

**`group_role` n'est pas un argument d'émission — il est résolu.** Le service interroge le dépôt
d'appartenances de BACK-16 au moment où il signe, et refuse d'émettre si aucune appartenance n'est
active. `active_group_id`, lui, reste un argument — l'appelant dit où il veut travailler — mais il
est confronté au dépôt avant d'entrer dans le jeton. Aucune signature de méthode ne permet donc de
se déclarer gérant : la règle n'est pas écrite dans une docstring, elle est **inexprimable**.

**Un seul instant est figé pour toute l'émission.** Le même alimente `iat`, `exp` et la date à
laquelle l'appartenance est jugée active. Deux appels à l'horloge produiraient un jeton affirmant
qu'une appartenance était active à un instant qui n'est pas celui qu'il porte.

**Le rôle vaut jusqu'à quinze minutes.** `group_role` est figé pour la durée du jeton d'accès. C'est
un choix de latence assumé : une rétrogradation met au plus une durée d'access token à produire son
effet, et l'urgence est couverte par la révocation de BACK-10d. Les rôles de périmètre **clinique**,
eux, ne sont jamais dans un jeton — ils se résolvent à la requête (BACK-10c), parce qu'un
vétérinaire change de clinique dans la journée.

**Les claims d'un jeton de rafraîchissement ne font jamais autorité.** Ils disent ce qui était vrai
il y a jusqu'à sept jours. Tout renouvellement repasse par `create_access_token`, donc par la
vérification d'appartenance. Recopier les claims d'un rafraîchissement dans un jeton d'accès
figerait un rôle une semaine et viderait de son sens le budget de quinze minutes ci-dessus. La règle
est écrite dans le port ; c'est BACK-29 qui devra la tenir.

**Les cinq permissivités de PyJWT sont corrigées explicitement** : clause `require` sur les sept
claims obligatoires, `strict_aud`, `enforce_minimum_key_length` à la signature comme à la
vérification, liste d'algorithmes fermée dérivée d'un `Literal` de configuration, et une tolérance
d'horloge de dix secondes — assez pour absorber la dérive entre deux instances derrière un
répartiteur, trop peu pour prolonger utilement un jeton expiré.

**Toute borne de configuration se mesure dans l'unité de la règle, et suit ce dont elle dépend.** La
première version de ce ticket bornait la clé de signature à 32 **caractères**, pour les trois
algorithmes. La revue contradictoire du code l'a mise en défaut par l'exécution : une clé de 32
octets avec HS384 validait, le service démarrait, et **chaque** émission levait une `InvalidKeyError`
— exactement le défaut que le `Literal` venait de fermer pour RS256. La borne est donc indexée par
l'algorithme (32 / 48 / 64 octets) et comptée en octets. Les durées de vie ont gagné une borne haute
pour la même raison : `iat + durée` finit par déborder la date, et le service aurait démarré avant
d'échouer à chaque émission.

**Ce qui n'est pas passé en argument est vérifié, et ce qui est passé est confronté.** `account_type`
est confronté à la table des audiences à l'émission — un type inconnu produirait un jeton
parfaitement signé que ce même service refuserait ensuite de relire. Et l'invariant « `group_role` et
`active_group_id` sont nuls ensemble ou renseignés ensemble », que l'émission tient par
construction, est **revérifié au décodage** : un rôle sans périmètre est précisément la combinaison
qu'une garde d'autorisation mal écrite accepterait.

## Alternatives écartées

### Un champ « type de compte » sans audience

Le jeton porte `account_type`, chaque route le lit. Écartée parce qu'elle repose entièrement sur la
**discipline de chaque route** : la première qui oublie la vérification ouvre l'API professionnelle
aux jetons de particuliers. L'audience, elle, est vérifiée par la bibliothèque de signature
elle-même, avant qu'une ligne de code métier ne s'exécute.

### Un port partagé dédié à la lecture des appartenances

Le premier plan prévoyait un huitième port dans `shared/domain/ports/`, son adaptateur dans
`organization`, sa doublure en mémoire et sa suite de conformité. Écartée après vérification :
`GroupRole` est un `StrEnum`, donc **est** une chaîne, et la signature de
`MembershipRepository.find_active_role` satisfait telle quelle un alias de fonction. L'anti-corruption
n'aurait rien converti, et son adaptateur aurait été une enveloppe d'une ligne sans consommateur. Le
service reçoit donc un `ActiveGroupRoleResolver` — même parti que `Clock` dans les doublures : il
n'y a rien à nommer de plus qu'une fonction.

### Une catégorie d'erreur d'authentification et un statut 401 dans le traducteur

Écartée parce que la question était **déjà tranchée** : BACK-09 a prévu que « les futurs 401
d'authentification (BACK-10) » sortent par `HTTPException`, dont le handler dédié préserve les
en-têtes — le `WWW-Authenticate` compris. BACK-10a définit donc le **vocabulaire** d'erreurs, et
BACK-10c, qui tient la bordure HTTP, posera le statut. Une seule exception y échappe :
`InactiveMembershipError` hérite aussi de `NotFoundError`, par la règle de non-divulgation — un 403
confirmerait au demandeur que le groupe existe.

### Un claim `iss` et un en-tête `kid`

Écartés faute de besoin actuel. Le ticket énumère ses neuf claims et `iss` n'y figure pas :
l'audience partitionne déjà les trois applications d'un émetteur unique. Le `kid` aurait préparé la
rotation de clé, mais une rotation reste de toute façon une **coupure** tant que les jetons en
circulation n'en portent pas — et BACK-10d apporte la révocation ciblée, qui est le vrai levier.

## Conséquences

**Ce que le service gagne.** Une isolation qui ne dépend plus de la vigilance de chaque route.
L'impossibilité, par construction de signature, de fabriquer un jeton dont le rôle ou le groupe
n'ont pas été vérifiés. Et un décodage qui distingue quatre refus — expiré, signature invalide,
mauvais type, audience incorrecte — au lieu d'un « jeton invalide » indifférencié.

**Ce qu'il paie.** Une lecture en base à chaque émission portant un groupe actif : le login et le
rafraîchissement coûtent une requête de plus. Trois variables d'environnement supplémentaires, à
tenir cohérentes entre l'API et les trois frontends. Jusqu'à quinze minutes de latence sur une
rétrogradation. Et une rotation de `JWT_SECRET_KEY` qui reste une coupure : toutes les sessions
tombent, refresh de sept jours compris — et, depuis BACK-17, les codes de vérification en cours avec
elles.

**Ce qui reste ouvert.** Le montage : la dépendance FastAPI qui assemble le service et l'unité de
travail d'`organization` ne peut vivre ni dans `shared`, qui n'a pas le droit d'importer un module,
ni dans un module, qui n'a pas le droit d'en connaître un autre. Seul `main.py` le peut, et c'est
BACK-10c qui tranchera la forme. Restent aussi la révocation par `jti` (BACK-10d), le jeton de
portée réduite `group_selection` (BACK-10e) et la confrontation audience ↔ type de compte au
parcours de connexion (BACK-29).

## Références

- `backend/api/src/app/shared/domain/ports/token_service.py` — le port, ses neuf claims et ses
  erreurs.
- `backend/api/src/app/shared/infrastructure/security/jwt_service.py` — l'adaptateur, et les cinq
  options qui corrigent les défauts de PyJWT.
- `backend/api/src/app/core/config.py` — les trois audiences, la famille HMAC, la longueur minimale
  de clé par algorithme et les bornes de durée de vie.
