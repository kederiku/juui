---
title: ADR-0020 — Un code OTP se hache et se poivre, son magasin échoue fermé, et il naît dans le worker
description: Le code de vérification n'est jamais stocké en clair ni transporté par la file ; son magasin lève quand Redis tombe, au lieu de dégrader comme le cache.
---

# ADR-0020 — Un code OTP se hache et se poivre, son magasin échoue fermé, et il naît dans le worker

| Statut      | Date       | Tickets                                                |
| ----------- | ---------- | ------------------------------------------------------ |
| **Accepté** | 2026-08-26 | BACK-17, BACK-22, BACK-28 (à venir), BACK-31 (à venir) |

## Contexte

Décision rendue par BACK-17, qui livre la vérification d'adresse e-mail par code à usage unique.
Trois questions se posaient, et chacune avait une réponse « évidente » qui ne tenait pas à
l'examen.

**Où vit le code ?** Un OTP est un secret d'authentification : le stocker en clair dans Redis, le
temps de sa validité, reviendrait à y laisser un mot de passe temporaire. Mais le hacher ne suffit
pas non plus — un condensé nu de six chiffres se casse par force brute exhaustive en une fraction
de seconde, un million de SHA-256 étant l'affaire de quelques millisecondes.

**Que fait le magasin quand Redis tombe ?** Le [port `Cache`](../backend/cache.md) (BACK-14) répond
déjà à cette question, et sa réponse est la dégradation gracieuse : `get` rend « absent », `exists`
rend `False`, le service continue plus lentement. Sa propre docstring désigne BACK-17 pour dire que
ce contrat **ne convient pas** ici : « cet OTP a-t-il été consommé ? » répondu « non » par défaut
ouvre la porte que le mécanisme entier existe pour fermer.

**Où le code est-il engendré ?** L'envoi part en tâche de fond (BACK-15) — la requête HTTP ne doit
pas attendre le SMTP. La lecture naturelle du ticket engendre le code dans le cas d'usage puis le
passe à la tâche ; or un argument de tâche voyage **en clair** dans le stream Redis, que BACK-15
borne en nombre d'entrées mais jamais en durée. Le secret se retrouverait à côté de son propre
condensé, dans la même instance, et survivrait à sa propre expiration.

## Décision

**Le magasin d'OTP ne conserve qu'une empreinte HMAC-SHA256 poivrée, il lève au lieu de dégrader,
et le code est engendré dans le worker — la file ne transporte qu'un identifiant de compte.**

Concrètement :

- ce qui est écrit dans Redis est `HMAC(poivre, "{account_id}:{code}")`. Le poivre est **dérivé**
  de `JWT_SECRET_KEY` par un HMAC portant une étiquette de séparation de domaine — une clé
  indépendante, qui ne vit pas dans Redis, et sans laquelle le hachage ne protégerait rien.
  L'identifiant de compte entre dans l'empreinte : sans lui, deux comptes ayant tiré le même code
  — une fois sur un million, donc souvent — porteraient la même empreinte ;
- le code est tiré par `secrets.randbelow`, jamais par `random`, et manipulé comme une **chaîne**
  de bout en bout : « 004271 » est un code à six chiffres, pas le nombre 4271 ;
- la comparaison passe par `hmac.compare_digest`, en temps constant, et se fait **côté service** —
  le `==` de Lua, côté Redis, s'arrête au premier octet différent ;
- toute panne du magasin lève `OtpStoreUnavailableError`, un `RuntimeError` qui suit le chemin 500
  générique : il n'existe aucun verdict par défaut. C'est aussi ce qui interdit de contourner les
  quotas de renvoi en faisant tomber Redis ;
- la consommation d'une tentative et les trois contrôles de renvoi sont des **scripts Lua** :
  indivisibles, ils interdisent à deux requêtes concurrentes de dépenser la même tentative, et à un
  refus de consommer un quota ;
- le code naît dans le worker. Le cas d'usage appelé par l'API contrôle et met en file
  (`OtpDispatcher`) ; celui qui s'exécute dans le worker tire, range et remet (`OtpStore`,
  `OtpSender`). Trois ports là où la carte du ticket en annonçait deux, et c'est la sécurité qui
  paie le troisième.

## Alternatives écartées

### Réutiliser le port `Cache` de BACK-14

Il est déjà là, il parle déjà à Redis, et son décorateur `@cached` est prêt. Mais son contrat est
l'inverse de celui qu'il faut : il dégrade en silence, et son propre auteur l'a écrit noir sur
blanc à l'intention de ce ticket. Un magasin de sécurité bâti sur un port qui répond « je ne sais
pas » par « non » n'est pas un magasin de sécurité. Ses clés portent en outre un segment de
**tenance** obligatoire, or une vérification d'adresse se joue à l'inscription, avant toute
appartenance à un groupe : composer la clé par lui lèverait `MissingTenantContextError` sur le
parcours le plus banal du service.

### Un condensé nu, sans poivre

Six chiffres, c'est un espace de 10⁶. Une table de correspondance complète se calcule en quelques
millisecondes, et se recalcule pour chaque compte puisque l'identifiant entre dans l'empreinte —
sans que cela change rien à l'ordre de grandeur. Sans une clé absente du stockage, hacher ne fait
que déplacer le secret.

### Une variable `OTP_SECRET_KEY` dédiée

Plus orthodoxe, et rejetée pour son coût : un secret de plus à distribuer, à faire tourner et à
oublier, dans un gabarit d'environnement qui en compte déjà. SETUP-08, qui recense les variables
OTP à publier, n'en annonce d'ailleurs aucune. La dérivation donne la même indépendance
cryptographique pour zéro variable, et son seul effet de bord est assumé : faire tourner
`JWT_SECRET_KEY` invalide les codes en cours, qui vivent dix minutes.

### Engendrer le code côté API et le passer à la tâche

C'est la lecture littérale du ticket, et c'est un port de moins. Mais le code en clair traverserait
alors la file, dans une instance Redis qui détient déjà son condensé — ce qui annule le bénéfice du
hachage pendant toute la durée de vie du message, laquelle n'est bornée que par `MAXLEN`, jamais par
une durée. Le troisième port coûte une abstraction ; l'alternative coûte le secret.

### Une base Redis dédiée aux magasins de sécurité

INFRA-02 fixe deux bases : la 0 pour le cache, la 1 pour le broker. Une base 2 aurait isolé les
clés d'OTP d'une future politique `volatile-lru`, qui n'évince que les clés porteuses d'un TTL —
ce qu'elles sont toutes. Écartée pour aujourd'hui : `maxmemory` vaut zéro, donc rien n'est évincé,
et l'ajout d'une base est une décision d'infrastructure qui appartient à INFRA-02. Un code évincé
se lit comme un code expiré, sans conséquence ; c'est un **compteur de renvoi** évincé qui rouvrirait
un quota, et c'est cela qu'il faudra reprendre le jour où `maxmemory` cessera d'être nul.

## Conséquences

Ce que le service gagne : un stockage dont la lecture ne donne rien, un magasin qui ne s'ouvre pas
quand il tombe, et un secret qui n'existe que dans le processus qui l'envoie.

Ce qu'il paie : un troisième pool Redis (client dédié, contrat opposé à celui du cache), un port de
plus dans le domaine d'`identity`, et une dépendance de la validité des codes à la clé de signature
des jetons.

Ce qui reste ouvert : la [réinitialisation de mot de passe](../backend/verification-email-otp.md)
(BACK-31) doit traiter son jeton exactement comme un OTP — la carte du ticket le dit déjà.

**BACK-22 a repris l'adaptateur SMTP provisoire écrit ici**, sans toucher au port `OtpSender`,
comme annoncé : le dialogue est descendu en port technique de `shared/`
([ADR-0022](./0022-transport-email-partage.md)). Il a en revanche confirmé, plutôt qu'infirmé, ce
que cet ADR pose : le code de vérification **ne passe pas** par le module `notifications`, un
événement de notification voyageant par cette même file sans TTL
([ADR-0021](./0021-notification-par-evenement.md)).
