---
title: Configuration
description: Les Settings Pydantic — neuf sous-modèles, valeurs dérivées, .env strict — et la validation au démarrage.
---

# Configuration

Le service ne lit jamais son environnement à la volée — toute la configuration passe par un
objet `Settings` Pydantic, découpé en neuf sous-modèles et validé dès le démarrage. Cette
page décrit ce découpage, les valeurs dérivées, la strictesse du fichier `.env` et les sondes qui vérifient l'ensemble.

Toute la configuration du service tient dans un objet unique,
`Settings`, typé et validé **au démarrage** : aucun `os.getenv`
n'a sa place ailleurs dans le code. Une variable obligatoire absente arrête le processus en
la nommant, plutôt que de produire une panne au premier appel HTTP.

Les valeurs viennent de deux sources — les variables d'environnement du processus, comme les
recevra le conteneur d'INFRA-04, et le fichier `backend/api/.env` pour un lancement sur le
poste. Ce que signifie chaque variable est écrit dans `.env.example`, son
gabarit ; cette page ne le recopie pas, pour éviter que les deux divergent.

## Les neuf sous-modèles

| Sous-modèle        | Préfixe     | Ce qu'il porte                                        | Consommé par                                 |
| ------------------ | ----------- | ----------------------------------------------------- | -------------------------------------------- |
| `AppSettings`      | _aucun_     | environnement, niveau de log, origines CORS           | BACK-08 (environnement), BACK-11 (CORS, log) |
| `DatabaseSettings` | `POSTGRES_` | connexion PostgreSQL                                  | BACK-05                                      |
| `RedisSettings`    | `REDIS_`    | connexion Redis, bases de cache et de broker          | BACK-14, BACK-15                             |
| `S3Settings`       | `S3_`       | stockage objet, MinIO en dev et Amazon S3 en prod     | BACK-13                                      |
| `JWTSettings`      | `JWT_`      | clé de signature, algorithme, durées de vie           | BACK-10                                      |
| `OtpSettings`      | `OTP_`      | validité, tentatives et quotas de renvoi d'un OTP     | BACK-17                                      |
| `SmtpSettings`     | `SMTP_`     | courriel sortant, plus `MAIL_FROM` sans préfixe       | BACK-17, repris par BACK-22                  |
| `PasswordSettings` | `PASSWORD_` | coût du hachage argon2id, plancher OWASP dans le type | BACK-10b                                     |
| `HibpSettings`     | `HIBP_`     | adresse et délai total du contrôle de fuite           | BACK-10b                                     |

Un préfixe par sous-modèle plutôt qu'un délimiteur de nesting : `POSTGRES_USER` et
`MINIO_ROOT_USER` sont imposés par les images Docker, et la traduction n'aurait servi à rien.
L'arbitrage remonte à SETUP-05, il est consigné au
[registre des écarts](../ecarts/setup.md#écarts-assumés-avec-le-ticket-setup-05).

L'accès se fait par sous-modèle : `settings.app.environment`, `settings.db.host`,
`settings.redis.cache_db`, `settings.s3.bucket`, `settings.jwt.algorithm`,
`settings.otp.ttl_seconds`, `settings.smtp.host`.

`MAIL_FROM` est lu par `SmtpSettings` **sans** le préfixe `SMTP_`, par un alias — c'est le nom
que publie le gabarit depuis INFRA-07, et le même mécanisme que `MINIO_ROOT_USER` chez
`S3Settings`.

**Sept variables n'ont aucun défaut**, et sont donc obligatoires : `POSTGRES_USER`,
`POSTGRES_PASSWORD`, `POSTGRES_DB`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET` et
`JWT_SECRET_KEY`. Elles désignent une base, un bucket ou une clé réels — leur donner un
défaut ne ferait que retarder l'échec jusqu'à la première requête. Toutes les autres portent
une valeur de développement, ce qui rend la copie du gabarit suffisante.

Les secrets sont typés `SecretStr`. Ils n'apparaissent ni dans un `repr`, ni dans
`model_dump(mode="json")` où ils sortent en `'**********'` — leur valeur ne s'obtient que par
un `get_secret_value()` explicite.

## Valeurs dérivées

Les URLs ne se saisissent pas, elles se recomposent à partir de leurs composants. C'est ce
qui évite la seconde source de vérité qu'aurait été un `DATABASE_URL` écrit à la main à côté
d'un `POSTGRES_PASSWORD` : les deux divergeraient au premier changement de mot de passe.

| Propriété                    | Valeur                                  |
| ---------------------------- | --------------------------------------- |
| `settings.db.sqlalchemy_url` | `postgresql+asyncpg://…` — pour BACK-05 |
| `settings.redis.cache_url`   | base `REDIS_CACHE_DB` — pour BACK-14    |
| `settings.redis.broker_url`  | base `REDIS_BROKER_DB` — pour BACK-15   |

Ce sont des **propriétés** et non des champs calculés, à dessein : le mot de passe y figure
en clair, et une propriété n'entre ni dans le `repr` ni dans `model_dump()`. Ne jamais les
journaliser telles quelles.

## Le fichier `.env` est strict

Une clé que ce fichier porte sans qu'aucun champ ne la réclame **empêche le démarrage**, en
la nommant. C'est ce que promet `.env.example`, et c'est ce qui en fait le
miroir exact des champs de `Settings` : une variable qui y figure sans exister dans le code
se signale au premier `uvicorn`, pas six mois plus tard. D'où l'interdiction d'y recopier le
`.env` de la racine — `COMPOSE_PROJECT_NAME` ou `PGADMIN_DEFAULT_EMAIL` suffiraient à bloquer
l'API.

La contrainte est **à sens unique**. Les variables d'environnement du _processus_ sont, elles,
filtrées sur les champs déclarés : le conteneur d'INFRA-04 pourra recevoir tout le `.env` de
la racine, `POSTGRES_HOST_PORT` et `MINIO_API_HOST_PORT` compris, sans que rien ne bronche.

pydantic-settings ne sait pas tenir cette promesse seul : chaque sous-modèle ne voit que son
préfixe, et personne ne surveille le reste du fichier. La source `_OrphanKeyDotEnvSource` de
`config.py` comble ce trou en une douzaine de lignes, et le jeu des
clés admises se calcule par introspection des sous-modèles — il n'y a aucune liste à tenir à
jour à la main.

## Dans le code

`get_settings()` construit `Settings` une seule fois (`@lru_cache`) et s'utilise comme
dépendance FastAPI. L'alias `SettingsDep` évite de répéter l'annotation :

```python
from app.core import SettingsDep


@router.get("/exemple")
def exemple(settings: SettingsDep) -> str:
    return settings.app.environment
```

En test, la dépendance se remplace sans toucher à l'environnement du processus :

```python
app.dependency_overrides[get_settings] = lambda: settings_de_test
```

`get_settings.cache_clear()` remet le cache à zéro entre deux cas.

## Vérifier que le filet tient

Trois sondes, dans le même esprit que celle de [Mypy](./qualite-et-typage.md#mypy). La première met le `.env` de
côté, puis le remet — le `;` garantit la restauration même en cas d'échec :

```bash
mv .env .env.hors-service ; uv run python -c 'from app.core import get_settings; get_settings()' ; mv .env.hors-service .env
```

Attendu : les sept variables obligatoires listées **d'un seul coup**, chacune sous son nom
d'environnement — et non un `user Field required` qui laisserait deviner le préfixe.

La deuxième ajoute une clé étrangère au fichier, après l'avoir sauvegardé :

```bash
cp .env .env.sonde && echo 'PGADMIN_DEFAULT_EMAIL=dev@example.com' >> .env ; uv run python -c 'from app.core import get_settings; get_settings()' ; mv .env.sonde .env
```

Attendu : `PGADMIN_DEFAULT_EMAIL : cle inconnue -- aucun champ de Settings ne la reclame`.

La troisième montre le masquage des secrets, puis la surcharge de la dépendance :

```bash
uv run python - <<'PY'
import asyncio

import httpx
from fastapi import FastAPI
from pydantic import SecretStr

from app.core import AppSettings, DatabaseSettings, JWTSettings, S3Settings, Settings, SettingsDep, get_settings

print(repr(get_settings().jwt))

application = FastAPI()


@application.get("/sonde")
def sonde(settings: SettingsDep) -> str:
    return settings.s3.bucket


async def appeler() -> str:
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://sonde") as client:
        return (await client.get("/sonde")).json()


print("sans surcharge :", asyncio.run(appeler()))

application.dependency_overrides[get_settings] = lambda: Settings(
    app=AppSettings(environment="staging"),
    db=DatabaseSettings(user="u", password=SecretStr("p"), db="d"),
    s3=S3Settings(access_key=SecretStr("a"), secret_key=SecretStr("s"), bucket="bucket-de-test"),
    jwt=JWTSettings(secret_key=SecretStr("k")),
)
print("avec surcharge :", asyncio.run(appeler()))
PY
```

Attendu : `secret_key=SecretStr('**********')`, puis `juui-dev` et `bucket-de-test`.

Les écarts assumés avec le ticket BACK-03 sont consignés au
[registre des écarts](../ecarts/back.md#écarts-assumés-avec-le-ticket-back-03).
