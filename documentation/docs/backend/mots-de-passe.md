---
title: Mots de passe
description: 'La politique 14–128 sans contrainte de composition, le hachage argon2id, et un contrôle de fuite en k-anonymity qui accepte quand il est muet.'
---

# Mots de passe

Trois briques, livrées par BACK-10b : l'objet-valeur `Password`, qui porte la politique du cahier
des charges ; l'adaptateur argon2id du port `PasswordHasher` ; et l'adaptateur Have I Been Pwned du
port `BreachChecker`, posé par BACK-06c. Aucun compte ne porte encore d'empreinte — le champ, la
colonne et la migration arrivent avec BACK-28, dans le commit qui les remplit.

La décision d'ensemble est instruite dans l'[ADR-0025](../adr/0025-politique-de-mot-de-passe-et-degradation-hibp.md).

## La politique tient en une ligne, et c'est délibéré

Entre **14 et 128 caractères, bornes incluses**. Aucune contrainte de composition : ni majuscule,
ni chiffre, ni caractère spécial.

Ce n'est pas un oubli mais l'alignement sur le NIST (SP 800-63B). Exiger une composition produit
`Motdepasse1!` à la chaîne — des secrets plus courts, plus prévisibles, moins bien mémorisés, et
notés sur un papier. La longueur, elle, achète de l'entropie sans rien coûter à personne.

Deux conséquences à connaître :

- **Le comptage est en points de code**, pas en octets — quatorze octets feraient un plancher de
  cinq idéogrammes — ni en graphèmes, qui demanderaient une dépendance pour rien. C'est aussi ce
  que compte le `min_length` de Pydantic, si bien que la bordure HTTP et le domaine comptent la
  même chose.
- **Aucune normalisation Unicode.** Ni élagage, ni casse, ni NFKC. La normalisation de
  compatibilité _réduit_ l'entropie — « ﬁ » et « fi » deviendraient le même secret — et normaliser
  à l'inscription en l'oubliant à la réinitialisation enferme l'utilisateur dehors, sans que
  personne le voie avant que ça arrive.

## On n'obtient pas un `Password` sans avoir demandé le contrôle de fuite

C'est la pièce qui répond à la phrase du ticket — « pour que la règle ne soit pas dupliquée entre
inscription, réinitialisation et changement de mot de passe » :

```python
password = await Password.create(saisie, breach_checker=checker)   # la seule fabrique
Password(saisie)                                                   # TypeError
```

Le constructeur direct refuse. Un parcours qui voudrait sauter le contrôle de fuite doit donc passer
une doublure explicite — ce qui est un **acte**, visible en revue, et non une omission. Le script de
semis d'INFRA-08 est dans ce cas, et c'est légitime : les mots de passe de démonstration sont
publiquement documentés, le verdict n'aurait aucun sens, et un script de semis ne doit pas dépendre
du réseau.

Ce que `Password` promet : la longueur a été vérifiée, et le contrôle de fuite a été **demandé**.
Ce qu'il ne promet pas : que le mot de passe soit absent des fuites — le port dégrade quand le
service tiers est muet, et le type mentirait s'il prétendait l'inverse.

**La politique ne s'applique pas à la connexion.** On l'applique à l'inscription, à la
réinitialisation et au changement. Refuser un mot de passe existant parce que la borne a bougé
dirait à un attaquant, avant tout contrôle d'identifiant, que ce compte-là vaut la peine — et
interroger le service de fuites à chaque connexion lui enverrait un préfixe du vrai mot de passe de
chaque utilisateur, plusieurs fois par jour.

## Le hachage : argon2id, et pourquoi pas bcrypt

Le ticket autorisait l'un ou l'autre. bcrypt **tronque silencieusement à 72 octets** : avec une
politique qui va jusqu'à 128 caractères, tout le haut de la plage serait décoratif, et deux mots de
passe longs partageant leurs 72 premiers octets deviendraient interchangeables — sans qu'aucune
erreur ne se produise nulle part. Il n'est par ailleurs pas dur en mémoire, ce qui le rend amical
pour un attaquant équipé de cartes graphiques.

Les coûts par défaut sont la **configuration recommandée par l'OWASP** : `m=19456 KiB` (19 Mio),
`t=2`, `p=1`, condensé de 32 octets, sel de 16 octets. Mesuré sur un poste de développement :
**~17 ms par hachage**.

Deux d'entre eux sont réglables, `PASSWORD_ARGON2_TIME_COST` et `PASSWORD_ARGON2_MEMORY_COST_KIB`,
et l'API refuse de démarrer **sous** la recommandation OWASP. Le plancher n'est pas de la rigidité :
le service réhache automatiquement à la connexion quand les coûts changent, si bien qu'abaisser la
valeur ne produirait pas seulement des empreintes neuves faibles — cela dégraderait activement
toutes les anciennes, compte par compte, à mesure que leurs propriétaires se connectent.

Le parallélisme n'est pas réglable : les cinq configurations de l'OWASP le fixent à 1, et
argon2-cffi calcule ses voies à la suite — un `p` élevé découperait la même mémoire en tranches
sans rien acheter au défenseur.

:::warning Le chiffre qui compte n'est pas la milliseconde, c'est le mébioctet
Le calcul sort de la boucle d'événements par `asyncio.to_thread`, dont le vivier est plafonné à
`min(32, cœurs + 4)`. Le pic mémoire du service vaut donc ce plafond multiplié par le coût mémoire
d'un hachage : sur une machine à quatorze cœurs, **dix-huit fils à 19 Mio font 342 Mio**. Les mêmes à 64 Mio en feraient 1,1 Gio, sur
une route que personne n'a encore eu besoin d'authentifier. Monter `PASSWORD_ARGON2_MEMORY_COST_KIB`
déplace ce plafond — c'est à peser avant de le faire.
:::

### La remise à niveau vit dans `verify`

```python
outcome = await hasher.verify(stored=account.password_hash, candidate=saisie)
if not outcome.verified:
    raise InvalidCredentialsError(...)
if outcome.refreshed_hash is not None:
    ...  # à persister, hors du chemin qui décide de la connexion
```

Il n'y a **pas** de `needs_rehash()` public, et c'est une décision. Un tel appel obligerait le cas
d'usage de connexion à rehacher lui-même, donc à fabriquer un `Password` à partir de la saisie — sur
un chemin où la politique ne s'applique pas. Le jour où la borne basse passerait de 14 à 16, tout
compte créé avec quatorze caractères verrait sa connexion échouer, et seulement ceux dont l'empreinte
est périmée : exactement ceux que la remise à niveau devait servir.

L'échec du rehachage n'est jamais propagé : `refreshed_hash` vaut alors `None`, un avertissement est
journalisé, et la tentative se rejouera à la connexion suivante. Une connexion valide ne se perd pas
pour une remise à niveau.

## Le contrôle de fuite : k-anonymity, et dégradation permissive

Le mot de passe est condensé en SHA-1 ; **seuls les cinq premiers caractères** de l'empreinte
quittent le processus. Le service rend le millier de suffixes partageant ce préfixe, et la
comparaison se fait localement. Ni le mot de passe, ni son empreinte complète, ni même le suffixe ne
sortent jamais.

| Détail                                                                             | Pourquoi                                                                                                                                                                                                                                 |
| ---------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| En-tête `Add-Padding: true`                                                        | Sans lui, la **taille** de la réponse varie avec le seau : un observateur du flux TLS corrèle la longueur au préfixe et resserre les vingt bits que la k-anonymity protège.                                                              |
| Verdict = suffixe présent **et compte > 0**                                        | Corollaire du rembourrage : les entrées ajoutées portent un compte nul. « Mon suffixe est-il dans le corps ? » rendrait un faux positif.                                                                                                 |
| En-tête `User-Agent` nommé                                                         | Le service répond 403 à un client anonyme — et notre propre dégradation avalerait ce 403 en silence, désactivant le contrôle pour toujours.                                                                                              |
| Comparaison par `hmac.compare_digest`, sans `break`                                | Ce qui ne doit pas fuir n'est pas le verdict, mais la **position** du suffixe dans le seau. Même règle que `codes_match` pour l'OTP.                                                                                                     |
| En-tête `Accept-Encoding: identity`                                                | `aiter_bytes()` rend des octets **déjà décompressés** : sans cela, un corps de 199 Kio qui se détend en 200 Mio est entièrement matérialisé avant le moindre contrôle de budget — 437 Mio de pic mesurés.                                |
| Plafond de 512 Kio sur la réponse                                                  | `HIBP_API_URL` est réglable, donc l'hôte au bout n'est pas de confiance. La valeur vaut dix fois un seau rembourré : la première, posée à 64 Kio sur une arithmétique fausse, **coupait des seaux légitimes** — et couper vaut accepter. |
| Une ligne n'est « exploitable » que si son suffixe fait 35 caractères hexadécimaux | Sinon `Retry:30`, dans une page de maintenance, compte pour une entrée valide et la dégradation devient **muette**.                                                                                                                      |
| Enveloppe `asyncio.timeout`                                                        | Voir l'encadré ci-dessous.                                                                                                                                                                                                               |

:::danger Le délai de la bibliothèque HTTP ne borne pas ce qu'on croit
`httpx.Timeout(2.0)` fixe deux secondes **par phase** — connexion, lecture, écriture, attente de
pool — et le délai de lecture **se réarme à chaque fragment reçu**. Un serveur qui envoie un octet
toutes les 1,5 s tient donc la requête ouverte indéfiniment : **mesuré à 30,1 s pour un délai
annoncé à 2 s**. L'adaptateur pose donc une enveloppe `asyncio.timeout` par-dessus, et c'est elle
qui tient la promesse du ticket. Sans elle, `POST /auth/register` — non authentifié — deviendrait un
amplificateur de déni de service, et la dégradation ne se déclencherait jamais : on ne dégraderait
pas, on se figerait.
:::

**Muet vaut accepté, jamais en silence.** Toute réponse inexploitable — panne de transport, statut
non-200, corps illisible, dépassement du budget d'octets — rend `False` et émet un avertissement.
C'est la seule dégradation permissive du service : refuser une inscription parce qu'un tiers ne
répond pas coûte plus cher que le risque couvert. Elle ne se généralise pas — le magasin d'OTP, lui,
échoue fermé, et l'[ADR-0020](../adr/0020-otp-hache-et-echec-ferme.md) dit pourquoi.

Il n'y a **pas** de `HIBP_ENABLED`. Un interrupteur qui désactive un contrôle de sécurité depuis
l'environnement finit posé un jour d'incident et n'en repart jamais. Hors ligne, le service dégrade
tout seul, en le journalisant.

### Ce que la bibliothèque journalisait, et que nous ne journalisions pas

`httpx` écrit à INFO une ligne `HTTP Request: GET https://api.pwnedpasswords.com/range/2EA84` —
c'est-à-dire le préfixe d'empreinte déposé dans les journaux du service, quoi que fasse
l'adaptateur. Cinq caractères de SHA-1 croisés avec le corpus public réduisent le mot de passe d'un
utilisateur à un millionième de ce corpus. Le défaut a été **trouvé en exécutant la suite de tests**,
et le remède est un plancher absolu sur `httpx` et `httpcore` dans
[`core/logging.py`](./journalisation.md) : `LOG_LEVEL=DEBUG` ne le rouvre pas.

## Les erreurs

| Code                        | Statut | Quand                                          |
| --------------------------- | ------ | ---------------------------------------------- |
| `shared.password.too_short` | 422    | Moins de 14 points de code.                    |
| `shared.password.too_long`  | 422    | Plus de 128 points de code.                    |
| `shared.password.breached`  | 422    | Le mot de passe figure dans une fuite connue.  |
| `shared.password.invalid`   | 422    | Racine des trois, pour les attraper d'un coup. |

Les erreurs **techniques** du hachage — `PasswordHashingError` et ses deux filles — sont des
`RuntimeError` hors de la hiérarchie `DomainError`, comme `EmailDeliveryError` et
`TokenIssuanceError` : elles sortent en 500, avec leur trace. En particulier,
`StoredPasswordHashInvalidError` **lève** au lieu de rendre « non vérifié » : rendre faux sur une
colonne corrompue transformerait « notre base est abîmée » en « tous ces gens se trompent de mot de
passe », c'est-à-dire une panne totale diagnostiquée comme une erreur d'utilisateur.

Aucun refus ne porte la saisie : `details` ne contient que les **bornes**, jamais une mesure du
secret — il sort tel quel dans le corps de la réponse, donc dans les journaux de tous les clients.
Et le refus HIBP ne dit jamais **combien de fois** le mot de passe a fuité : ce nombre ferait de
notre formulaire un oracle gratuit sur le corpus.

:::info Pour FRONT-13 : deux formes coexistent, et une seule est propre à ce ticket
Sur une route HTTP, la borne de longueur sera portée par le schéma Pydantic de BACK-28, donc
**Pydantic refusera avant le domaine** : le corps portera `code: "http.request.validation_error"`
avec `details.errors[0].type == "string_too_short"` et un `msg` en anglais. Les codes
`shared.password.too_short` et `too_long` n'apparaissent que sur les chemins qui ne passent pas par
un schéma HTTP — un script, une tâche de fond.

**Le seul code à brancher spécifiquement est donc `shared.password.breached`** ; le reste est le 422
générique déjà traité. Les bornes n'entreront dans le Zod généré par Orval qu'avec BACK-28 : Orval
génère depuis les _opérations_, et aucune route ne prend encore de mot de passe.
:::

## Ce que la relecture du code a corrigé, et qui vaut d'être su

Cinq défauts ont été trouvés **en exécutant**, pas en relisant. Ils sont tous du même genre : un
garde-fou qui semblait tenir, et qui laissait passer.

| Défaut                                                  | Ce qu'il produisait                                                                                                                                                                                                                                                                                |
| ------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Le jeton de fabrique était un **champ** de la dataclass | `dataclasses.replace(password, value=<mot de passe connu fuité>)` rendait un `Password` valide sans un seul appel au contrôle ; `copy`, `deepcopy` et `pickle` sautaient `__post_init__` entièrement. Le drapeau vit désormais dans le contexte d'appel, et les trois voies de copie sont fermées. |
| Le plafond de réponse était à 64 Kio                    | Un seau réel rembourré (1 800 lignes, 68,6 Kio) était **coupé**, donc le mot de passe accepté — pour tous les mots de passe de ce préfixe, et de façon permanente.                                                                                                                                 |
| httpx annonçait `gzip, deflate`                         | Le plafond d'octets ne bornait rien : 199 Kio compressés se détendaient en 200 Mio, matérialisés avant tout contrôle.                                                                                                                                                                              |
| Une ligne `Retry:30` comptait pour une entrée valide    | Deux pages d'erreur HTML sur trois dégradaient **sans un mot**, ce que le port interdit nommément.                                                                                                                                                                                                 |
| Le journal portait `netloc` et non `hostname`           | Un miroir interne derrière une authentification basique déposait son mot de passe dans les journaux à chaque dégradation.                                                                                                                                                                          |

Chacun a son test de non-régression, écrit à partir du cas qui l'a révélé.

## Ce que ce ticket ne livre pas

- **Le champ `Account.password_hash`, sa colonne et sa migration** : BACK-28, dans le commit qui les
  remplit. Une colonne nullable que rien n'écrit serait une régression permanente, et la forme sûre
  se décide avec le parcours d'inscription en face. La forme attendue est dans la docstring de
  `PasswordHash` : `String(255)`, jamais `String(97)` — une empreinte aux paramètres actuels fait
  exactement 97 caractères, et dimensionner dessus transformerait la première montée de coût en
  troncature silencieuse.
- **La vérification factice sur compte inconnu** : BACK-29. Sans elle, la réponse part en ~1 ms pour
  une adresse inconnue et ~15 ms pour une adresse connue — le formulaire de connexion devient un
  énumérateur de comptes, et défait la non-divulgation que le service tient partout ailleurs. Le
  remède tient en une ligne, et la constante existe pour cela :
  `await hasher.hash(DECOY_PASSWORD)`, en jetant le résultat.
- **La limitation de cadence** devant les routes qui hachent : BACK-29 et INFRA-04. C'est elle, et
  non un plafond de concurrence maison, qui répond à l'abus de volume.
- **Le câblage FastAPI** des deux adaptateurs : BACK-28. (BACK-10c a monté celui des jetons, pas ceux-ci.) Les fabriques
  `build_password_hasher(settings)` et `build_breach_checker(settings)` sont autonomes et servent
  l'API, le worker et le semis à l'identique.

## Vérifier que les règles tiennent

```bash
cd backend/api && uv run pytest -m passwords -v
```

Attendu : 97 tests, aucun réseau, aucun conteneur. Un garde-fou `autouse` du conftest racine refuse
toute requête HTTP vers un hôte tiers dans **toute** la suite — le critère « aucun test n'appelle le
vrai service de fuites » est mécanique, pas conventionnel.

```bash
cd backend/api && make imports
```

Attendu : `Contracts: 5 kept, 0 broken.` C'est là que se verrait un import d'`argon2` ou d'`httpx`
depuis le domaine.

```bash
cd backend/api && HIBP_API_URL=https://127.0.0.1:1 uv run python -c "
import asyncio, logging
logging.basicConfig(level=logging.WARNING)
from app.core.config import Settings
from app.shared.infrastructure.clients.hibp import build_breach_checker
print(asyncio.run(build_breach_checker(Settings()).is_breached('un-mot-de-passe-honnete')))
"
```

Attendu : un avertissement `Controle de fuite indisponible sur 127.0.0.1:1 (ConnectError)`, puis
`False` — le mot de passe est accepté, et la dégradation s'est vue.
