---
title: Vérification d'adresse (OTP)
description: 'Le code à six chiffres : engendré dans le worker, stocké haché et poivré, à usage unique, borné en tentatives et en renvois — et un magasin qui échoue fermé.'
---

# Vérification d'adresse par code OTP

À l'issue de l'inscription, l'adresse e-mail d'un compte est vérifiée par un **code à six
chiffres**, envoyé par courriel et valable dix minutes. Cette page décrit le parcours, ce que le
service stocke réellement, et les propriétés qui font la différence entre un code de vérification
et un simple nombre envoyé par mail.

Le compte reste **ACTIF** tant que son adresse n'est pas vérifiée : il peut s'authentifier, mais
reste retenu sur l'écran de vérification. Confondre les deux états enfermerait dehors l'utilisateur
qui vient de s'inscrire, sans aucun moyen de demander un nouveau code.

## Le parcours, en trois cas d'usage

```
API (BACK-28 plus tard)                worker TaskIQ
  RequestEmailVerificationOtp            identity.otp.send_verification
    1. le compte existe, non vérifié       └─ IssueEmailVerificationOtp
    2. le tourniquet des renvois                4. generate_otp_code()      secrets
    3. OtpDispatcher.dispatch ─────────►        5. OtpStore.issue(hash)     Redis, TTL
                                                6. OtpSender.send(code)     SMTP → Mailpit
  VerifyEmailOtp
    7. OtpStore.consume — tentative atomique, comparaison en temps constant
    8. account.verify_email() puis commit, dans la même transaction
```

Le découpage n'est pas cosmétique : **le code naît dans le worker**. Un argument de tâche voyage en
clair dans le stream Redis, que [BACK-15](./taches-de-fond.md) borne en nombre d'entrées mais jamais
en durée ; engendrer le code du côté qui répond en HTTP obligerait à le passer à la tâche,
c'est-à-dire à déposer le secret à côté de son propre condensé. La file ne transporte qu'un
**identifiant de compte**. L'argumentaire complet est dans
l'[ADR-0020](../adr/0020-otp-hache-et-echec-ferme.md).

## Trois ports, et pourquoi trois

| Port            | Ce qu'il promet                                            | Adaptateur                           |
| --------------- | ---------------------------------------------------------- | ------------------------------------ |
| `OtpStore`      | ranger, dépenser une tentative, tenir les quotas de renvoi | `RedisOtpStore` — base 0, pool dédié |
| `OtpSender`     | faire parvenir six chiffres à une adresse                  | `EmailOtpSender` — via `shared`      |
| `OtpDispatcher` | faire partir une demande hors du fil de la requête         | `TaskOtpDispatcher` — TaskIQ         |

La carte du ticket en annonçait deux ; le troisième est le prix de la décision ci-dessus. Sans lui,
un cas d'usage devrait importer `infrastructure/tasks/`, ce que le contrat `module-layers`
([Qualité et typage](./qualite-et-typage.md)) refuse.

BACK-17 avait écrit son propre dialogue SMTP dans `identity`, à titre **provisoire** et en le
déclarant. **BACK-22 l'a repris** : le dialogue vit désormais dans
`shared/infrastructure/clients/smtp_mailer.py`, derrière le port technique `EmailTransport`
([ADR-0022](../adr/0022-transport-email-partage.md)). Ce qui reste dans `identity` est la
composition du message de vérification, et le port `OtpSender` n'a pas bougé d'une ligne — c'est
exactement ce qu'un port doit permettre.

**L'OTP ne passe pas pour autant par le module [`notifications`](./notifications.md)**, contrairement
à ce que la carte de BACK-17 annonçait, et le motif est celui de cette page : un événement de
notification voyage par la file, où tout argument reste lisible en clair dans un stream sans TTL.
Un code de vérification est un secret ; il est engendré dans le worker et remis depuis le worker.
La règle qu'il illustre, elle, est bien celle de `notifications` : **un OTP est transactionnel**, il
part quelles que soient les préférences — et son expéditeur n'en consulte aucune.

## Ce que Redis tient, et ce qu'il ne tient pas

Jamais le code. Un document par compte, portant une **empreinte HMAC-SHA256 poivrée** et le nombre
de tentatives restantes :

```
dev:otp:verify:{account_id}   →  { fingerprint, attempts_left }   TTL = OTP_TTL_SECONDS
dev:otp:resend:gate:{id}      →  délai minimal entre deux envois
dev:otp:resend:account:{id}   →  plafond de renvois par compte, fenêtre glissante
dev:otp:resend:ip:{sha256}    →  plafond de renvois par IP — l'adresse réduite à une empreinte
```

Le poivre est **dérivé** de `JWT_SECRET_KEY` par un HMAC portant une étiquette de séparation de
domaine : une clé indépendante, qui ne vit pas dans Redis. C'est elle qui rend le hachage utile — un
condensé nu de six chiffres se casse par force brute exhaustive en une fraction de seconde.
Corollaire assumé : faire tourner `JWT_SECRET_KEY` invalide les codes en cours, qui vivent dix
minutes.

Les clés **ne passent pas** par le compositeur de [cache](./cache.md) et ne portent donc aucun
segment de tenance : un OTP appartient à un compte, pas à une structure, et la vérification se joue
à l'inscription — avant toute appartenance à un groupe. Composer la clé par lui lèverait
`MissingTenantContextError` sur le parcours le plus banal du service.

L'adresse IP, elle, entre dans la clé sous forme d'empreinte : une clé se lit dans `MONITOR`, dans
le `SLOWLOG` et dans toute console d'inspection, et un compteur n'a pas besoin de savoir qui il
compte.

## Le magasin échoue fermé

C'est la propriété qui le distingue du [cache](./cache.md), et la docstring du port `Cache`
désignait déjà ce ticket pour le dire.

| Redis ne répond plus | Le port `Cache` (BACK-14) | Le port `OtpStore` (BACK-17) |
| -------------------- | ------------------------- | ---------------------------- |
| lecture              | rend « absent »           | **lève**                     |
| écriture             | sans effet, silencieuse   | **lève**                     |
| présence             | rend `False`              | **lève**                     |
| sonde `ping()`       | journalise, ne lève pas   | journalise, ne lève pas      |

`OtpStoreUnavailableError` est un `RuntimeError`, pas une `DomainError` : elle suit le chemin 500
générique ([Erreurs](./erreurs.md)) au lieu de se déguiser en refus métier. Un service qui répond
500 est désagréable et honnête ; un service qui répond « ce code n'a pas été consommé » parce que
Redis est tombé est confortable et faux. C'est aussi ce qui interdit de contourner les quotas de
renvoi en faisant tomber Redis.

Seule la sonde de démarrage ne lève pas : un Redis absent ne doit pas priver le service de tout ce
qui ne touche pas à la vérification d'adresse.

## Trois tentatives, puis le code meurt

Le décrément d'une tentative et la lecture de l'empreinte forment **une seule opération
indivisible** — un script Lua. Deux requêtes concurrentes ne peuvent pas dépenser la même tentative,
faute de quoi trois essais en deviendraient trente, lancés en parallèle.

Le script porte aussi une garde qui n'est pas facultative : `HINCRBY` sur une clé **absente** la
crée, et sans TTL. Vérifier un code inexistant laisserait derrière lui un document éternel, dans une
instance où toute clé doit expirer.

La comparaison, elle, se fait **côté service**, par `hmac.compare_digest` : le `==` de Lua s'arrête
au premier octet différent, et sa durée trahirait le nombre de caractères corrects.

## Le tourniquet des renvois

Trois contrôles, indivisibles eux aussi, et qui **ne consomment rien quand l'un d'eux refuse** —
sans quoi un double-clic franchirait le délai minimal puis brûlerait quand même une unité du plafond
horaire.

| Contrôle           | Variable                          | Ce qu'il protège                                 |
| ------------------ | --------------------------------- | ------------------------------------------------ |
| délai minimal      | `OTP_RESEND_MIN_INTERVAL_SECONDS` | le double-clic et le « rien reçu » impatient     |
| plafond par compte | `OTP_RESEND_MAX_PER_EMAIL`        | le titulaire de l'adresse, contre le harcèlement |
| plafond par IP     | `OTP_RESEND_MAX_PER_IP`           | le service, contre l'arrosage de mille adresses  |

Le plafond par IP ne vaut que ce que vaut l'IP vue par l'API : derrière un proxy,
`FORWARDED_ALLOW_IPS` mal renseignée fait paraître toutes les requêtes venues du proxy, et le
plafond devient **global**. Une demande sans IP — hors requête HTTP — ignore ce contrôle plutôt que
de tomber dans un seau commun, qui bloquerait tout le monde dès le premier appelant.

Le refus sort en **429** avec l'en-tête `Retry-After` : c'est la catégorie que BACK-17 ajoute au
tableau de [BACK-09](./erreurs.md). Le message ne dit ni lequel des trois contrôles a parlé, ni
combien d'unités restent.

## Un seul refus pour trois situations

| Ce qui s'est passé    | Ce que le service répond                        |
| --------------------- | ----------------------------------------------- |
| code faux             | `identity.otp.invalid_code` — 422               |
| code expiré           | `identity.otp.invalid_code` — **même message**  |
| aucun code en cours   | `identity.otp.invalid_code` — **même message**  |
| tentatives épuisées   | `identity.otp.attempts_exhausted` — 429         |
| adresse déjà vérifiée | `identity.account.email_already_verified` — 409 |

Distinguer « expiré » de « faux » dirait à un attaquant qu'il a trouvé le bon moment, sinon le bon
code ; distinguer « aucun code » révélerait qu'aucune demande n'est en cours. Le blocage, lui, **se
dit** : ce que l'utilisateur doit savoir n'est pas si son code était faux, mais qu'insister ne sert
plus à rien. Le compteur restant ne sort jamais. La même règle est reprise par FRONT-17 pour l'écran
2FA.

Deux refus arrivent **avant** que la tentative ne soit dépensée : un identifiant sans compte et une
adresse déjà vérifiée. Sans cet ordre, un tiers épuiserait le quota de tentatives de son voisin par
des appels sans objet.

## Ce qui n'est pas encore branché

Aucune route HTTP n'expose ces cas d'usage : la portée du ticket s'arrête aux cas d'usage et à leurs
adaptateurs. `POST /auth/register` (BACK-28) appellera le premier juste après avoir créé le compte,
et l'écran de vérification appellera le second — une fois que les dépendances d'authentification
(BACK-10c) sauront poser l'identifiant de compte à partir du jeton. D'ici là, un endpoint qui
prendrait cet identifiant dans son corps serait un oracle d'existence de compte, et une cible de
force brute distribuée.

Le blocage sur l'écran de vérification appartient lui aussi à BACK-10c :
`get_current_active_account` refusera un compte suspendu et retiendra un compte non vérifié. Ce que
ce ticket garantit, c'est l'état qu'elle lira — `status = ACTIVE`, `email_verified = False`.

## Vérifier que le parcours tient

**1. La suite de tests dédiée.** Depuis `backend/api/`, la pile levée :

```bash
uv run pytest -m otp -q
```

Elle couvre l'adaptateur Redis contre un vrai Redis — TTL réellement posé, décrément indivisible,
absence de clé fantôme, échec fermé contre un port où personne n'écoute — et le parcours de bout en
bout par Mailpit. Les tests de règles, eux, tournent sans Docker :
`uv run pytest tests/modules/identity -q`.

**2. Ce que Redis tient vraiment.** La sonde ci-dessous émet un code, relit le document par un
client brut, puis épuise le parcours :

```python
import asyncio
from uuid import uuid4

from redis.asyncio import Redis

from app.core import get_settings
from app.modules.identity.domain.policies import generate_otp_code
from app.modules.identity.infrastructure.clients.redis_otp_store import (
    build_otp_rules,
    build_otp_store,
)
from app.shared.infrastructure.clients.cache_keys import environment_slug


async def main() -> None:
    settings = get_settings()
    store = build_otp_store(settings)
    raw = Redis.from_url(settings.redis.cache_url, decode_responses=True)
    account_id = uuid4()
    rules = build_otp_rules(settings)

    code = generate_otp_code()
    await store.issue(account_id=account_id, code=code, rules=rules)

    key = f"{environment_slug(settings.app.environment)}:otp:verify:{account_id}"
    document = await raw.hgetall(key)
    print(f"0. code emis            : {code}")
    print(f"1. cle                  : {key}")
    print(f"2. document Redis       : {document}")
    print(f"3. duree de vie         : {await raw.ttl(key)} s")
    print(f"4. code en clair present: {code in str(document)}")

    faux = [(await store.consume(account_id=account_id, code="000000")).value for _ in range(2)]
    print(f"5. deux essais faux     : {faux}")
    bon = (await store.consume(account_id=account_id, code=code)).value
    rejoue = (await store.consume(account_id=account_id, code=code)).value
    print(f"6. bon code             : {bon}")
    print(f"7. rejoue               : {rejoue}")
    print(f"8. cle restante         : {await raw.exists(key)}")

    await raw.aclose()
    await store.aclose()


asyncio.run(main())
```

```
0. code emis            : 190953
1. cle                  : dev:otp:verify:a7c04ff0-fe67-400c-8ad2-f1df203deb3e
2. document Redis       : {'fingerprint': '5c2fdc2341ded766de642239a462980d9b0d9d96320d4cf8fea04934abc164f6', 'attempts_left': '3'}
3. duree de vie         : 600 s
4. code en clair present: False
5. deux essais faux     : ['rejected', 'rejected']
6. bon code             : accepted
7. rejoue               : rejected
8. cle restante         : 0
```

Les lignes qui comptent : **4** — ce qui est stocké ne laisse pas relire le secret ; **7** — le code
ne sert qu'une fois ; **8** — il est détruit, pas seulement marqué.

**3. Les tentatives et les quotas.** Même forme, en remplaçant le corps par trois essais faux, puis
un renvoi immédiat, puis quatre comptes distincts derrière une seule IP :

```
0. trois essais faux     : ['rejected', 'rejected', 'exhausted']
1. bon code apres coup   : rejected
2. premier renvoi        : ResendVerdict(allowed=True, retry_after_seconds=None)
3. renvoi immediat       : ResendVerdict(allowed=False, retry_after_seconds=60)
4. quatre comptes, une IP: [True, True, True, False]
```

La ligne **1** est celle qu'on vient vérifier : passé le quota, le **bon** code ne vaut plus rien —
le document est détruit, pas mis en attente. La ligne **4** montre le plafond par IP faisant son
office là où trois plafonds par compte n'auraient rien vu.

**4. Le message part réellement.** La pile levée, le test de bout en bout écrit dans la vraie boîte :

```bash
uv run pytest tests/modules/identity/test_otp_email_delivery.py -q
```

Il émet par SMTP, relit le message dans l'**API HTTP de Mailpit** (`/api/v1/search`), en extrait le
code et vérifie le compte avec. Relire Redis testerait ce que le code a écrit ; relire Mailpit teste
ce que l'utilisateur a reçu. La boîte s'ouvre par `make mail` depuis la racine.

**5. La tâche est bien découverte par le worker.**

```python
from app.shared.infrastructure.tasks.broker import broker
from app.shared.infrastructure.tasks.discovery import discover_module_tasks

print(discover_module_tasks())
print(sorted(broker.get_all_tasks()))
```

```
('app.modules.identity.infrastructure.tasks',)
['identity.otp.send_verification', 'shared.demo.fail_on_purpose', 'shared.demo.record_ping']
```

`identity` est le premier module à déclarer un sous-paquet de tâches : le mécanisme de BACK-15
s'applique tel quel, sans toucher ni au Dockerfile ni au compose.

Les écarts assumés avec le ticket BACK-17 sont consignés au
[registre des écarts](../ecarts/back.md#écarts-assumés-avec-le-ticket-back-17).
