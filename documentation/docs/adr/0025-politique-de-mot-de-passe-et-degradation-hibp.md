---
title: 'ADR-0025 — Un mot de passe se juge sur sa seule longueur, et un contrôle de fuite muet le laisse passer'
description: 'Politique NIST sans contrainte de composition, hachage argon2id derrière un port, et dégradation permissive du contrôle Have I Been Pwned.'
---

# ADR-0025 — Un mot de passe se juge sur sa seule longueur, et un contrôle de fuite muet le laisse passer

| Statut      | Date       | Tickets                                                 |
| ----------- | ---------- | ------------------------------------------------------- |
| **Accepté** | 2026-08-27 | BACK-10b, BACK-28, BACK-29, BACK-31, FRONT-13 (à venir) |

## Contexte

Décision rendue par BACK-10b, qui livre la brique d'authentification par mot de passe : l'objet-valeur
`Password`, le hachage argon2id derrière le port `PasswordHasher`, et l'adaptateur Have I Been Pwned
du port `BreachChecker` posé par BACK-06c.

Le cahier des charges donne la règle — « longueur strictement comprise entre 14 et 128 caractères,
aucune contrainte de composition » — et l'aligne explicitement sur les recommandations du NIST. Il
demande aussi une vérification en k-anonymity contre les fuites publiques, et une dégradation
gracieuse quand le service tiers est injoignable. Ce qu'il ne dit pas, et qui a dû être tranché, est
la forme : où vit la règle, ce qui empêche un parcours de l'oublier, et ce que le service fait
exactement quand une réponse arrive mal.

Six tickets consommeront cette brique — BACK-28 (inscription), BACK-29 (connexion), BACK-31
(réinitialisation), BACK-18 (2FA), INFRA-08 (jeu de démonstration) et FRONT-13 (champ de saisie).
Aucun compte du dépôt ne porte encore d'empreinte : le champ, la colonne et la migration
appartiennent à BACK-28.

## Décision

**La politique est la longueur, et rien d'autre.** Entre 14 et 128 caractères, bornes incluses, sans
contrainte de composition. Le NIST (SP 800-63B) a raison contre l'intuition : exiger une majuscule,
un chiffre et un caractère spécial produit `Motdepasse1!` à la chaîne, c'est-à-dire des secrets plus
courts, plus prévisibles, moins bien mémorisés et plus souvent notés. La longueur achète de
l'entropie sans rien coûter à personne. La lecture « strictement comprise » du cahier des charges
n'est pas suivie à la lettre — elle n'admettrait que 15 à 127, refuserait un mot de passe de 128
caractères sorti d'un gestionnaire, et contredirait la checklist du ticket, qui écrit « 14–128 ».

**Le comptage est en points de code, et aucune normalisation Unicode n'est appliquée.** Compter des
octets ferait de quatorze un plancher de cinq idéogrammes ; compter des graphèmes demanderait une
dépendance pour un gain nul. Quant à NFKC, que le NIST recommande pourtant : la normalisation de
compatibilité **réduit** l'entropie — « ﬁ » et « fi » deviennent le même secret — ce qu'OWASP
proscrit explicitement ; et normaliser à l'inscription en l'oubliant à la réinitialisation enferme
l'utilisateur dehors, sans que l'oubli se voie avant qu'il frappe. BACK-06c avait déjà tranché ce
point pour le port voisin : « un mot de passe ne se normalise pas ».

**Un `Password` ne s'obtient qu'en demandant le contrôle de fuite.** Le constructeur direct refuse ;
la seule fabrique est `Password.create(saisie, breach_checker=...)`, dont l'argument est obligatoire.
C'est ce qui répond à la phrase du ticket — « pour que la règle ne soit pas dupliquée entre
inscription, réinitialisation et changement ». Une règle qui ne tient que par une docstring est une
règle qu'un quatrième parcours oubliera, et l'oubli ne laisse aucune trace ; ici il échoue au premier
test. Une doublure explicite reste possible — le semis d'INFRA-08 en pose une — mais c'est alors un
acte, visible en revue.

**Le type est ce qui garantit qu'on ne hache que ce qui a passé la politique.**
`PasswordHasher.hash()` prend un `Password`, jamais une chaîne. C'est la raison pour laquelle
l'objet-valeur vit dans `shared/domain/` et non dans `identity` comme une docstring l'annonçait : le
contrat `service-spaces` interdit à `app.shared` d'importer un module, si bien qu'un `Password` rangé
ailleurs aurait obligé le port à prendre un `str`, et la garantie aurait disparu avec le type.

**Le contrôle de fuite dégrade dans le sens permissif, et lui seul.** Toute réponse inexploitable —
panne de transport, statut non-200, corps illisible, dépassement du budget d'octets — accepte le mot
de passe et émet un avertissement. Refuser une inscription parce qu'un tiers ne répond pas coûte plus
cher que le risque couvert : un mot de passe faible qui passe est un compte à risque, une inscription
impossible est un service en panne pour tout le monde. Cette réponse ne se généralise pas : le
magasin d'OTP échoue fermé ([ADR-0020](./0020-otp-hache-et-echec-ferme.md)), et ce qui distingue les
deux n'est pas la famille du port mais ce que la réponse par défaut **autorise**.

**La dégradation n'est jamais silencieuse, et le budget de temps est un vrai budget.** Le délai de la
bibliothèque HTTP borne chaque _phase_ et se réarme à chaque fragment reçu : mesuré, 30,1 s pour un
délai annoncé à 2 s. Une enveloppe `asyncio.timeout` borne le total, sans quoi la route d'inscription
— non authentifiée — deviendrait un amplificateur de déni de service et la dégradation ne se
déclencherait jamais.

**La remise à niveau du hachage vit dans `verify`, qui rend un verdict structuré.** Un `needs_rehash()`
public obligerait le cas d'usage de connexion à rehacher lui-même, donc à fabriquer un `Password` à
partir d'une saisie sur un chemin où la politique ne s'applique pas : le jour où la borne basse
monterait, les comptes valides dont l'empreinte est périmée — exactement ceux que la remise à niveau
devait servir — verraient leur connexion échouer. L'adaptateur détient déjà les octets vérifiés ; il
rehache sans repasser par la politique, et l'échec du rehachage ne fait jamais échouer une connexion
valide.

**Les coûts argon2 sont réglables, avec un plancher dans le type.** Le ticket demande des coûts
configurables, et sans réglage la remise à niveau n'aurait aucun déclencheur autre qu'une livraison
de code. Mais un coût abaissable à distance, sur un service qui réhache automatiquement, ne produit
pas seulement des empreintes neuves faibles : il **dégrade activement les anciennes**, compte par
compte, à mesure que leurs propriétaires se connectent. Le plancher `ge=` à la configuration
recommandée par l'OWASP ferme cette manœuvre.

## Alternatives écartées

### bcrypt, que le ticket autorisait

Écartée pour un défaut mesurable : bcrypt **tronque silencieusement à 72 octets**. Avec une politique
qui va jusqu'à 128 caractères, tout le haut de la plage deviendrait décoratif, et deux mots de passe
longs partageant leurs 72 premiers octets deviendraient interchangeables — sans qu'aucune erreur ne
se produise nulle part. bcrypt n'est par ailleurs pas dur en mémoire, ce qui le rend amical pour un
attaquant équipé de cartes graphiques.

### Un `Password` rangé dans `identity/domain/policies.py`, comme le dépôt l'annonçait

C'était l'emplacement réservé par écrit, et l'[ADR-0022](./0022-transport-email-partage.md) plaide
dans ce sens : `shared/` est réservé aux besoins **techniques** qu'atteignent **deux** modules, or
tous les consommateurs de `Password` sont dans `identity`. Écartée après avoir écrit les deux
versions : le port `PasswordHasher` vit dans `shared/` par la portée du ticket, et le contrat
`service-spaces` lui interdit de nommer un type d'`identity`. Il aurait donc pris un `str`, et la
garantie « on ne hache que ce qui a passé la politique » — qui est l'essentiel de ce que ce ticket
apporte — aurait cessé d'être portée par le type. L'annonce contraire a été corrigée sur place, et
l'écart est consigné.

### Un `PasswordPolicy` séparé, orchestrant longueur puis fuite

Écartée parce que `shared/` n'a pas de couche `application` — le contrat `shared-layers` en fait deux
couches et non trois, et le commentaire qui l'accompagne dit pourquoi : « le noyau partagé n'orchestre
aucun cas d'usage ». Une classe de service installée là serait devenue le précédent que le prochain
ticket citerait. La fabrique de l'objet-valeur fait le même travail sans introduire de couche.

### Une suite de conformité pour `BreachChecker`

Envisagée, écrite, puis abandonnée. Le marqueur `conformance` du dépôt se déclare « suites jouées
contre l'implémentation réelle **et** sa doublure », et BACK-06c avait écrit noir sur blanc que les
tests propres aux doublures n'en portent aucun, « sinon `pytest -m conformance` annoncerait des tests
qui ne comparent rien ». Or le ticket interdit d'appeler le vrai service : la moitié « réelle » aurait
été pilotée par un transport de doublure, et la suite aurait opposé deux doublures. Le contrat du port
est épinglé des deux côtés à part — dans les tests de la doublure et dans ceux de l'adaptateur.

### Un plafond de concurrence maison devant le hachage

Écartée après avoir mesuré. Le vivier de `asyncio.to_thread` plafonne déjà les calculs simultanés à
`min(32, cœurs + 4)`, et le coût OWASP retenu ramène le pic à environ 342 Mio — un sémaphore
n'ajouterait qu'un second plafond, plus bas, transformant une saturation mémoire en file d'attente
non bornée sur la route la plus exposée. Le dépôt n'a par ailleurs aucun mécanisme de ce genre, et sa
réponse à l'abus de volume est écrite ailleurs : le refus en 429, que BACK-29 et INFRA-04 poseront
devant les routes concernées.

### Un réglage `HIBP_ENABLED`

Écartée par principe, et le principe mérite d'être écrit : un interrupteur qui désactive un contrôle
de sécurité depuis l'environnement finit posé un jour d'incident, et n'en repart jamais. Hors ligne,
le port dégrade déjà tout seul — on paie le délai, on obtient l'avertissement, et l'inscription passe.

## Conséquences

**Ce que le service gagne.** Une politique qu'un parcours ne peut pas contourner par distraction, et
qui s'écrit en une ligne chez l'appelant. Un hachage dont les coûts se lisent dans chaque empreinte,
se règlent sans livraison, et ne peuvent pas être abaissés sous l'état de l'art. Un contrôle de fuite
qui ne fait jamais tomber une inscription, et dont chaque défaillance laisse une trace.

**Ce qu'il paie.** Un objet-valeur qui vit ailleurs que là où le dépôt l'avait annoncé, et quatre
docstrings à corriger pour que le dépôt cesse de promettre ce qu'il ne fait pas. Une fabrique
asynchrone, donc un `await` dans des tests qui n'en demandaient pas. Deux dépendances applicatives de
plus, `argon2-cffi` et `httpx` promu depuis le groupe de développement. Et une règle de plus à
connaître : la politique ne s'applique jamais à la connexion.

**Ce qui reste ouvert.** La taille du corps HTTP n'est bornée nulle part dans le dépôt : la politique
protège argon2 et le contrôle de fuite, elle ne protège pas Starlette et Pydantic, qui auront déjà
construit la chaîne. C'est un sujet d'infrastructure, à ouvrir devant le proxy. La dégradation
permissive peut par ailleurs être **provoquée** — qui sait épuiser notre quota chez le service tiers
désactive le contrôle pour tout le monde ; l'avertissement est la seule chose qui le rende visible, et
le brancher sur une alerte appartient à l'observabilité.

## Références

- `backend/api/src/app/shared/domain/password.py` — l'objet-valeur, ses bornes et sa fabrique.
- `backend/api/src/app/shared/domain/ports/password_hasher.py` — le port, et ce qu'il laisse à BACK-29.
- `backend/api/src/app/shared/infrastructure/security/password.py` — l'adaptateur argon2id.
- `backend/api/src/app/shared/infrastructure/clients/hibp.py` — la k-anonymity et la dégradation.
- [Mots de passe](../backend/mots-de-passe.md) — la page d'usage, avec les sondes exécutables.
