# Juui

Plateforme SaaS B2B2C de prise de rendez-vous et de gestion pour cliniques
vétérinaires : agenda et gestion du cabinet côté professionnels, carnet de santé
numérique et réservation en ligne côté propriétaires d'animaux, back-office
d'administration côté plateforme.

## Arborescence du monorepo

| Dossier                           | Rôle                                                                                                                                             |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `docker/`                         | Configurations de conteneurisation : le `docker-compose.yml` qui assemble la pile, les Dockerfiles des services et les scripts d'initialisation. |
| `backend/api/`                    | Service d'API backend (FastAPI, architecture hexagonale et DDD).                                                                                 |
| `frontend/frontend-professional/` | Interface **B2B** — application des cliniques et des vétérinaires.                                                                               |
| `frontend/frontend-individual/`   | Interface **B2C** — application des propriétaires d'animaux.                                                                                     |
| `frontend/frontend-admin/`        | Interface d'**administration** — back-office de la plateforme.                                                                                   |
| `packages/`                       | Bibliothèques et composants partagés par les trois frontends (UI shadcn en mode monorepo, configurations communes, client API généré).           |
| `documentation/`                  | Documentation technique du projet, publiée avec Docusaurus.                                                                                      |

Les dossiers encore vides contiennent un `.gitkeep` afin que l'arborescence soit
versionnée dès maintenant : chacun sera rempli par le ticket qui lui correspond.

## Stack technique

- **Backend** — Python 3, FastAPI, Pydantic, PostgreSQL (pgAdmin en développement),
  SQLAlchemy, Alembic, PyJWT ; outillage `uv`, Ruff, Mypy, Pytest.
- **Frontend** — React, Next.js, TypeScript, TanStack Query, TanStack Form, Zod,
  Tailwind CSS, shadcn/ui ; outillage pnpm, ESLint, Prettier, Vitest, Orval.
- **Infrastructure** — Docker, Redis (broker et cache), MinIO en développement et
  Amazon S3 en production, TaskIQ pour les tâches de fond.

Le détail des choix et de leur justification se trouve dans le document
[Stack Technique et Architecture](https://docs.google.com/document/d/1m_16LSQk7WWyykR0nsbySHtD1M0HP3OTmc_KoB09bj0/edit).
Il sera repris et enrichi dans le site `documentation/`.

## Démarrage rapide

Une partie seulement de la pile démarre aujourd'hui : le service d'API, depuis
les tickets INFRA la base PostgreSQL avec sa console pgAdmin, Redis et le
stockage objet MinIO, et depuis FRONT-01 à FRONT-03 les trois interfaces —
professionnelle, grand public et back-office. La documentation arrive avec
DOC-01. Cette section décrit donc **deux parcours** — celui qui fonctionne
maintenant, puis la cible conteneurisée — et l'allocation de ports que cette
cible devra respecter.

### Prérequis

Pour le parcours qui fonctionne aujourd'hui :

- **Node 24 LTS** — la version de référence est déclarée dans [`.nvmrc`](.nvmrc) :
  avec `nvm` ou `fnm`, `nvm use` suffit à s'y aligner.
- **pnpm** — rien à installer soi-même : le champ `packageManager` du
  `package.json` racine épingle la version exacte, que pnpm récupère seul.
- **[`uv`](https://docs.astral.sh/uv/)** — uniquement pour `backend/api`. Il
  télécharge lui-même l'interpréteur Python attendu : rien d'autre à installer.

- **Docker** — [Docker Desktop](https://docs.docker.com/desktop/),
  [OrbStack](https://orbstack.dev/) ou [Colima](https://github.com/abiosoft/colima).
  Requis depuis INFRA-01 : c'est lui qui fait tourner PostgreSQL et pgAdmin. Qui
  veut seulement lancer `uvicorn` peut encore s'en passer — l'API n'ouvre aucune
  connexion à la base avant BACK-05. C'est bien `docker compose`, sous-commande
  du client, qui est attendue — pas l'ancien binaire `docker-compose`, qui n'est
  plus maintenu.

Un outil de plus pour le parcours conteneurisé complet. **Rien ne le réclame
encore** ; l'installer maintenant évite seulement d'avoir à revenir ici :

- **`make`** — sur macOS, il vient des Command Line Tools :
  `xcode-select --install`. La version 3.81 livrée par Apple suffit : c'est déjà
  elle qui exécute [`backend/api/Makefile`](backend/api/Makefile).

### Installation

```bash
git clone git@github.com:kederiku/juui.git && cd juui
```

Aucun `.env` n'est versionné — [`.gitignore`](.gitignore) les exclut tous et
n'excepte que les gabarits. Chaque fichier d'environnement se crée à partir du
sien, en retirant le suffixe `.example` :

| Gabarit versionné               | Fichier à créer    | Lu par                                 |
| ------------------------------- | ------------------ | -------------------------------------- |
| `.env.example`                  | `.env`             | `docker compose` — toute la pile       |
| `backend/api/.env.example`      | `backend/api/.env` | l'API lancée **hors** Docker (BACK-03) |
| `frontend/*/.env.local.example` | `.env.local`       | chaque application Next.js             |

```bash
cp .env.example .env
cp backend/api/.env.example backend/api/.env
```

Les valeurs livrées conviennent telles quelles sur un poste vierge : rien n'est
à modifier pour un premier démarrage. **Chaque variable est documentée dans son
gabarit** — les commentaires y font foi, ce README ne les recopie pas pour
éviter qu'ils divergent. Une seule mérite d'être changée dès qu'on quitte le
poste : `JWT_SECRET_KEY`, à régénérer par environnement avec
`openssl rand -hex 32`.

> **Note.** Des trois gabarits `frontend/*/.env.local.example`, seul celui de
> `frontend-professional` a aujourd'hui une application pour le lire. Sa copie
> n'est d'ailleurs pas nécessaire pour démarrer : les deux variables qu'il porte
> désignent l'API, que l'interface n'appelle pas encore (SHARED-03).

Le dépôt a **deux chaînes d'outils**, indépendantes l'une de l'autre.

Côté JavaScript, les workspaces pnpm — `frontend/*`, `packages/*` et
`documentation`, déclarés dans [`pnpm-workspace.yaml`](pnpm-workspace.yaml) :

```bash
pnpm install
```

Cette commande installe aussi les **hooks Git** — voir
[Hooks de pre-commit](#hooks-de-pre-commit).

Côté Python, le seul service `backend/api`, volontairement absent de ces
workspaces et piloté par `uv` :

```bash
cd backend/api && uv sync
```

### Démarrer aujourd'hui

Deux morceaux démarrent : les services d'infrastructure, en conteneurs, et
l'API, sur le poste.

D'abord l'infrastructure — PostgreSQL avec sa base de test `app_test` et la
console pgAdmin, Redis, et MinIO avec son bucket applicatif :

```bash
docker compose --project-directory . -f docker/docker-compose.yml up -d
```

Le `--project-directory .` n'est pas décoratif, et il n'est pas non plus
facultatif : le fichier compose vit dans `docker/` alors que le `.env` est à la
racine, et c'est ce drapeau qui accorde les deux. Il commande aussi la
résolution des chemins montés — le détail est dans
[`docker/docker-compose.yml`](docker/docker-compose.yml), en tête de fichier.

pgAdmin répond sur <http://localhost:5050> ; s'y connecter avec
`PGADMIN_DEFAULT_EMAIL` et `PGADMIN_DEFAULT_PASSWORD`. Le serveur
« Juui - PostgreSQL local » y est déjà enregistré, mot de passe compris : il n'y
a **rien à saisir** pour ouvrir la base. La console de MinIO, elle, répond sur
<http://localhost:9001> — voir « Vérifier le stockage objet » plus bas.

Puis l'API, hors conteneur tant qu'INFRA-04 n'a pas livré son image :

```bash
cd backend/api && uv run uvicorn app.main:app --reload
```

La documentation interactive répond sur <http://localhost:8000/docs>. L'API ne
sert encore aucune route — voir [`backend/api/README.md`](backend/api/README.md).
Elle ne parle pas encore à PostgreSQL non plus : le branchement de SQLAlchemy
est l'objet de BACK-05.

Depuis BACK-03, elle **valide sa configuration au démarrage** et refuse de partir
si une variable obligatoire manque — d'où la copie de `backend/api/.env` faite à
l'installation. Le message d'erreur nomme alors chaque variable en défaut.

Enfin les deux interfaces livrées, seuls workspaces pnpm à définir aujourd'hui
un script `dev` :

```bash
pnpm dev
```

La commande démarre en parallèle les serveurs de développement de tout le
dépôt : l'interface professionnelle répond sur <http://localhost:3001>, celle
des particuliers sur <http://localhost:3002> et le back-office sur
<http://localhost:3003> — ce dernier redirigeant aussitôt vers sa page de
connexion, voir [Le back-office de `frontend-admin`](#le-back-office-de-frontend-admin).
La documentation s'y ajoutera avec DOC-01, sur le port du tableau ci-dessous.

Pour n'en démarrer qu'une, la filtrer par le nom de son workspace :

```bash
pnpm --filter frontend-individual run dev
```

### La pile complète, avec Docker

> **Note.** Cette séquence n'est **pas encore opérationnelle**.
> [`docker/docker-compose.yml`](docker/docker-compose.yml) existe depuis
> INFRA-01 et porte aujourd'hui `postgres`, `pgadmin`, `redis`, `redisinsight`,
> `minio` et `minio-init` ; le `Makefile` de la racine, lui, n'existe pas —
> `make up` répondrait `No rule to make target 'up'`. La séquence figure ici
> parce qu'elle est le contrat que les tickets d'infrastructure doivent
> honorer : INFRA-04 et INFRA-05 s'ajoutent au même fichier compose, INFRA-06
> pose le Makefile qui l'enveloppe. À relire une fois INFRA-06 livré.

Une fois la pile conteneurisée en place, l'installation se réduira à trois
commandes :

```bash
git clone git@github.com:kederiku/juui.git && cd juui
cp .env.example .env
make up
```

| Cible                   | Effet                                       |
| ----------------------- | ------------------------------------------- |
| `make up`               | Démarre toute la pile en arrière-plan.      |
| `make down`             | Arrête la pile et libère les ports.         |
| `make logs service=api` | Suit les logs d'un service.                 |
| `make help`             | Cible par défaut : liste toutes les cibles. |

INFRA-06 en prévoit d'autres — migrations, seed, tests, shell dans un conteneur.
`make help` fera foi, comme dans [`backend/api/Makefile`](backend/api/Makefile),
qui adopte déjà ces conventions et auquel le Makefile racine n'aura qu'à
déléguer.

Le fichier compose vit dans `docker/`, le `.env` à la racine. Sans
`--project-directory`, `docker compose` chercherait son `.env` dans `docker/` et
n'en trouverait pas : c'est cette commande que `make up` encapsulera.

```bash
docker compose --project-directory . -f docker/docker-compose.yml up -d
```

Ajouter `--profile tools` pour démarrer en plus les consoles d'inspection
optionnelles — aujourd'hui RedisInsight, qui s'ouvre déjà raccordée aux deux
bases Redis.

> **Après modification d'un mot de passe dans `.env`.** PostgreSQL ne lit ses
> identifiants qu'à la **première** création de son volume : les changer ensuite
> reste sans effet jusqu'à un `docker compose down -v`, qui détruit les données
> au passage. La cible `make db-reset` (INFRA-06) fera cela proprement. MinIO,
> lui, relit les siens à chaque démarrage — un `restart` suffit, sans rien
> perdre.

Node et `uv` restent utiles sur le poste même avec ce parcours : les hooks de
pre-commit s'exécutent en dehors des conteneurs.

### Ports et URLs des services

Un port par service, réservé une fois pour toutes ici afin qu'aucun ticket n'ait
à en choisir un dans son coin :

| Service                       | Port hôte | Port interne | Arrive avec |
| ----------------------------- | --------- | ------------ | ----------- |
| API FastAPI                   | 8000      | 8000         | disponible  |
| `frontend-professional`       | 3001      | 3000         | disponible  |
| `frontend-individual`         | 3002      | 3000         | disponible  |
| `frontend-admin`              | 3003      | 3000         | disponible  |
| Documentation (Docusaurus)    | 3004      | —            | DOC-01      |
| PostgreSQL                    | 5432      | 5432         | disponible  |
| pgAdmin                       | 5050      | 80           | disponible  |
| Redis                         | 6379      | 6379         | disponible  |
| RedisInsight (profil `tools`) | 5540      | 5540         | disponible  |
| MinIO — API S3                | 9000      | 9000         | disponible  |
| MinIO — console web           | 9001      | 9001         | disponible  |
| Worker TaskIQ                 | aucun     | —            | BACK-15     |

Quelques choix méritent leur explication :

- **3000 n'apparaît pas.** C'est le port d'écoute interne des conteneurs
  Next.js, jamais publié : INFRA-05 le mappe sur 3001, 3002 et 3003 côté hôte.
  Ce sont donc les mêmes ports qu'en développement local — d'où la règle : ne
  pas lancer `pnpm dev` et `make up` en même temps.
- **pgAdmin sur 5050.** Ni SETUP-05 ni INFRA-01 ne fixaient ce port, et un
  tableau censé garantir l'absence de collision ne peut pas laisser de case
  vide : le choix a été fait ici, et INFRA-01 s'y est tenu. 5050 est le port des
  exemples Compose de pgAdmin — le moins surprenant — et il évite `8080`, déjà
  disputé par trop d'outils, comme les ports 5000 et 7000 que le récepteur
  AirPlay de macOS occupe par défaut.
- **RedisInsight sur 5540**, port d'écoute par défaut de l'image : le publier
  tel quel évite une correspondance de plus à retenir. Le service reste derrière
  le profil Compose `tools` et ne démarre donc pas avec `make up`.
- **Redis et RedisInsight ne sont publiés que sur `127.0.0.1`.** Les autres
  services le sont sur toutes les interfaces du poste ; ces deux-là non. Le
  Redis de développement n'a pas de mot de passe et la console n'a pas de page
  de connexion : les publier largement les offrirait en lecture et en écriture
  à tout le réseau auquel le poste est raccordé — un wifi partagé suffit. Rien
  ne change à l'usage, les URLs et les commandes restent celles de ce tableau.
- **Le worker n'écoute rien.** Il consomme la file Redis et n'ouvre aucun port
  entrant : rien à publier, rien à réserver.

Les ports publiés sur le poste sont tous **configurables** par une variable
`*_HOST_PORT` du `.env` : un PostgreSQL ou un Redis déjà installé localement se
contourne en changeant une ligne, sans rien toucher aux conteneurs, qui
continuent de se parler sur les ports internes.

Les adresses à ouvrir dans un navigateur :

| Service                         | URL                                  | Identifiants                                         |
| ------------------------------- | ------------------------------------ | ---------------------------------------------------- |
| API — documentation interactive | <http://localhost:8000/docs>         | —                                                    |
| API — contrat OpenAPI           | <http://localhost:8000/openapi.json> | —                                                    |
| `frontend-professional`         | <http://localhost:3001>              | —                                                    |
| `frontend-individual`           | <http://localhost:3002>              | —                                                    |
| `frontend-admin`                | <http://localhost:3003>              | —                                                    |
| Documentation                   | <http://localhost:3004>              | —                                                    |
| pgAdmin                         | <http://localhost:5050>              | `PGADMIN_DEFAULT_EMAIL` / `PGADMIN_DEFAULT_PASSWORD` |
| MinIO — console web             | <http://localhost:9001>              | `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD`            |
| RedisInsight                    | <http://localhost:5540>              | —                                                    |

PostgreSQL et Redis ne parlent pas HTTP : ils s'atteignent par une chaîne de
connexion, que l'API compose elle-même à partir des variables `POSTGRES_*` et
`REDIS_*`. Redis sépare ses usages par base — la base 0 pour le cache
applicatif, la base 1 pour le broker TaskIQ — et RedisInsight les présente comme
deux connexions distinctes, pré-remplies au démarrage.

Les identifiants ne sont pas recopiés ici, seulement nommés : leurs valeurs sont
celles du `.env`, dont [`.env.example`](.env.example) porte les exemples de
développement. Une seule source de vérité — un mot de passe écrit à deux
endroits finit toujours par diverger.

### Vérifier le stockage objet

MinIO tient lieu d'Amazon S3 sur le poste, et le bucket applicatif — `S3_BUCKET`,
`juui-dev` par défaut — est créé au démarrage par le service éphémère
`minio-init`. Celui-ci s'arrête une fois son travail fait : `docker compose ps`
le montre en `Exited (0)`, ce qui est le résultat attendu et non une panne. Son
journal dit exactement ce qu'il a fait :

```bash
docker compose --project-directory . -f docker/docker-compose.yml logs minio-init
```

La console web s'ouvre sur <http://localhost:9001>, avec `MINIO_ROOT_USER` et
`MINIO_ROOT_PASSWORD` pour identifiants. Depuis `RELEASE.2025-05-24T17-08-30Z`,
l'édition communautaire n'y conserve que le **navigateur d'objets** — parcourir
les buckets, téléverser, télécharger, supprimer. Les écrans d'administration
(utilisateurs, politiques, clés d'accès) sont passés à l'édition payante ;
`mc admin` les remplace.

Pour un aller-retour complet sans rien installer sur le poste — le conteneur
`minio-init` a déjà l'endpoint, les identifiants et le nom du bucket dans son
environnement :

```bash
docker compose --project-directory . -f docker/docker-compose.yml run --rm --entrypoint sh minio-init -c 'mc alias set t "$S3_ENDPOINT_URL" "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" && echo bonjour | mc pipe "t/$S3_BUCKET/essai.txt" && mc cat "t/$S3_BUCKET/essai.txt" && mc rm "t/$S3_BUCKET/essai.txt"'
```

Le bucket est **privé** : une requête anonyme sur un objet répond `403`. C'est
délibéré — BACK-13 servira les fichiers par des URLs pré-signées, qui portent
leur propre autorisation et expirent, plutôt que par un bucket ouvert en
lecture.

### Scripts racine

| Commande            | Effet                                                        |
| ------------------- | ------------------------------------------------------------ |
| `pnpm prepare`      | Installe les hooks Git. Lancé seul par `pnpm install`.       |
| `pnpm dev`          | Démarre en parallèle les serveurs de développement.          |
| `pnpm build`        | Construit chaque workspace, dans l'ordre de ses dépendances. |
| `pnpm lint`         | Analyse statique ESLint sur tout le dépôt.                   |
| `pnpm lint:fix`     | Idem, en appliquant les corrections automatiques.            |
| `pnpm typecheck`    | Vérification des types TypeScript.                           |
| `pnpm test`         | Suites de tests des workspaces.                              |
| `pnpm format`       | Reformate le dépôt avec Prettier.                            |
| `pnpm format:check` | Vérifie le formatage sans rien réécrire (CI).                |

`prepare` est un script de **cycle de vie** : personne ne le lance à la main,
pnpm s'en charge après chaque installation.

`dev`, `build`, `typecheck` et `test` délèguent aux workspaces qui définissent le
script de même nom ; ceux qui ne le définissent pas sont simplement ignorés.

`lint` et `format` fonctionnent autrement : ils parcourent le dépôt en une seule
passe depuis la racine. Depuis ESLint 10, la recherche de configuration part du
répertoire du **fichier analysé** et remonte l'arborescence — un `eslint .` lancé
à la racine applique donc déjà à chaque application sa propre configuration, et
celle de la racine au reste. Prettier procède de même. Déléguer aux workspaces
serait un double parcours, et laisserait de côté les fichiers de la racine, que
`pnpm -r` n'atteint pas.

> **Note.** Ces scripts ne couvrent que les workspaces pnpm ; le backend a les
> siens, décrits dans [`backend/api/README.md`](backend/api/README.md). Les
> cibles `make` qui réuniront les deux chaînes derrière une interface unique
> arrivent avec INFRA-06.

### Écarts assumés avec le ticket SETUP-05

| Écart                                                             | Raison                                                                                                                                                                                                                                                                       |
| ----------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Deux parcours au lieu de la seule séquence `make up`              | `make up` n'existe pas : le Makefile racine relève d'INFRA-06, qui dépend d'INFRA-05, donc de FRONT-01 à FRONT-03. Une séquence unique laisserait le nouvel arrivant sur `No rule to make target 'up'`.                                                                      |
| Docker et `make` signalés comme pas encore nécessaires            | Le ticket les liste en prérequis. Les présenter sans réserve ferait installer Docker Desktop à qui veut seulement lancer un `uvicorn`.                                                                                                                                       |
| `env_prefix` par sous-modèle plutôt que `env_nested_delimiter`    | BACK-03 prévoit `DB__`, `JWT__`… mais `POSTGRES_*`, `MINIO_ROOT_*` et `PGADMIN_DEFAULT_*` sont imposés par les images Docker. Le préfixe simple donne les mêmes sous-modèles sans couche de traduction.                                                                      |
| `ACCESS_TOKEN_EXPIRE_MINUTES` → `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | Pour que le bloc JWT tienne dans un unique `env_prefix`. Seul renommage appliqué à la liste du ticket.                                                                                                                                                                       |
| `DATABASE_URL` et `REDIS_URL` documentées mais commentées         | Valeurs dérivées : BACK-03 recompose l'URL à partir des composants. Les activer créerait une seconde source de vérité, qui divergerait au premier changement de mot de passe.                                                                                                |
| `.env.local.example` côté frontend plutôt que `.env.example`      | `.env` est ignoré par le [`.gitignore`](.gitignore) : `.env.local` est le seul fichier que Next.js puisse charger, et la règle « retirer `.example` » reste vraie partout.                                                                                                   |
| Port de pgAdmin fixé à 5050                                       | Ni SETUP-05 ni INFRA-01 ne le fixent. Un tableau qui doit garantir l'absence de collision ne peut pas laisser de case vide : le choix se fait ici, INFRA-01 en hérite.                                                                                                       |
| Deux services de plus que la liste du ticket                      | Le tableau ne vaut comme garantie d'absence de collision que s'il est exhaustif. DOC-01 réserve déjà 3004 et INFRA-02 prévoit RedisInsight — les omettre rendrait la garantie fausse.                                                                                        |
| Variables ajoutées hors de la liste du ticket                     | `CORS_ORIGINS` (BACK-11), `JWT_REFRESH_TOKEN_EXPIRE_DAYS` (BACK-10), `POSTGRES_TEST_DB` (INFRA-01), `REDIS_CACHE_DB` et `REDIS_BROKER_DB` (INFRA-02), `S3_REGION` (boto3), `API_INTERNAL_URL` (INFRA-05), `COMPOSE_PROJECT_NAME` et les `*_HOST_PORT` (INFRA-01 à INFRA-05). |
| Identifiants nommés par leur variable, jamais recopiés            | INFRA-03 demande de documenter ceux de la console MinIO. Les nommer renvoie à [`.env.example`](.env.example), seule source de vérité.                                                                                                                                        |

### Écarts assumés avec le ticket INFRA-01

| Écart                                                   | Raison                                                                                                                                                                                                                                                |
| ------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `postgres:18-alpine` au lieu de la 16 demandée          | Le ticket a été rédigé avant la sortie de la 18. Naître avec deux majeures de retard imposerait une migration avant même la première mise en production. Même arbitrage qu'en BACK-02, où Ruff cible `py314` là où le ticket disait `py312`.          |
| Volume monté sur `/var/lib/postgresql`                  | Depuis la 18, l'image place `PGDATA` dans `/var/lib/postgresql/18/docker` et déclare son volume sur le dossier parent. Le montage traditionnel sur `…/data` n'échoue pas : il perd les données en silence, ce que le critère de persistance interdit. |
| Script d'initialisation en `.sh` et non en `.sql`       | Le ticket dit « scripts SQL » ; [`.env.example`](.env.example) promet que `POSTGRES_TEST_DB` reste modifiable sans toucher au script. Un `.sql` déposé dans `/docker-entrypoint-initdb.d` n'interpole aucune variable — le shell, si.                 |
| `servers.json` inline plutôt que fichier versionné      | Un `.json` ne peut porter aucun commentaire, et il aurait figé `juui` et `5432` en dur à côté du `.env`. Le bloc `configs` du fichier compose interpole `${...}`, donc suit le `.env` sans seconde source de vérité.                                  |
| `PGPORT` ajouté au service `postgres`                   | Sans lui, `POSTGRES_PORT` ne serait qu'une décoration : le serveur écouterait 5432 quoi qu'il arrive, et la variable mentirait sur ce qu'elle décrit.                                                                                                 |
| `MASTER_PASSWORD_REQUIRED=False` et un fichier `pgpass` | Le ticket demande d'éviter la saisie manuelle. Sans le premier, pgAdmin réclame un mot de passe maître avant d'afficher quoi que ce soit ; sans le second, il réclame `POSTGRES_PASSWORD` à chaque ouverture de la connexion.                         |
| `REPLACE_SERVERS_ON_STARTUP=True`                       | Par défaut, la définition de serveur n'est lue qu'à la création du volume `pgadmin_data`. Un changement d'identifiants dans le `.env` n'atteindrait jamais la console sans un `down -v`.                                                              |
| Volume `pgadmin_data` nommé, `restart: unless-stopped`  | Le ticket demande « un volume » sans le nommer, et ne dit rien du redémarrage. Les deux suivent la convention posée pour `postgres`, que reprendront INFRA-02 à INFRA-05.                                                                             |
| Chemin monté écrit `./docker/postgres/init`             | `--project-directory .` déplace aussi la résolution des chemins relatifs, qui partent donc de la racine et non de `docker/`. Le fichier compose n'est utilisable que lancé ainsi — c'est écrit en tête de fichier.                                    |

### Écarts assumés avec le ticket INFRA-02

| Écart                                                                                     | Raison                                                                                                                                                                                                                                       |
| ----------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `redis:8-alpine` au lieu de la 7 demandée                                                 | Même arbitrage qu'en INFRA-01 avec `postgres:18`. Accessoirement une question de licence : la 8 est disponible sous AGPLv3, quand `7-alpine` résout vers la 7.4, passée sous RSALv2/SSPL.                                                    |
| Redis et RedisInsight publiés sur `127.0.0.1` seulement                                   | Contrairement à `postgres`, cette instance Redis n'a pas de mot de passe, et la console n'a pas de page de connexion. Une publication large les exposerait en écriture à tout le réseau du poste.                                            |
| Un `docker/redis/redis.conf` versionné plutôt que `--appendonly yes` en ligne de commande | Le ticket le donne pour optionnel. Raisonnement inverse de celui du `servers.json` inline d'INFRA-01 : un `.json` ne peut porter aucun commentaire, un `redis.conf` si — et l'essentiel de ce fichier tient dans ses raisons.                |
| Le port, lui, reste en ligne de commande                                                  | Un fichier de configuration Redis n'interpole aucune variable d'environnement. Y écrire `6379` créerait une seconde source de vérité à côté de `REDIS_PORT` ; la ligne de commande, elle, suit le `.env`.                                    |
| `maxmemory` volontairement non défini                                                     | Cache et broker partagent l'instance, et la politique d'éviction ignore les bases. Un `allkeys-*` supprimerait des tâches en attente sans la moindre erreur. Le raisonnement et la seule politique acceptable sont écrits dans `redis.conf`. |
| RedisInsight épinglé sur `3.8`                                                            | L'image ne publie pas de tag de majeure nue — `3` n'existe pas. La ligne mineure est le plus proche équivalent du `dpage/pgadmin4:9` d'INFRA-01.                                                                                             |
| Deux connexions pré-remplies dans RedisInsight                                            | Une aurait suffi. Deux font de la convention « base 0 = cache, base 1 = broker » quelque chose qui se voit en ouvrant la console, au lieu d'un commentaire de plus.                                                                          |
| Sonde de RedisInsight sur `127.0.0.1` et non `localhost`                                  | Le `/etc/hosts` du conteneur fait pointer `localhost` sur `127.0.0.1` **et** sur `::1` ; `wget` tente l'IPv6 d'abord, or la console n'écoute qu'en IPv4. Avec `localhost`, le service reste indéfiniment `unhealthy` tout en répondant.      |
| `REDIS_PASSWORD` déclarée mais sans effet côté serveur                                    | Variable cliente, consommée par BACK-14 et BACK-15. Lui donner un effet supposerait un `requirepass`, hors de propos pour une instance de développement qui n'est joignable que depuis le poste.                                             |

### Écarts assumés avec le ticket INFRA-03

| Écart                                                               | Raison                                                                                                                                                                                                                                                                                                                                                                                    |
| ------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `RELEASE.2025-09-07T16-13-09Z` épinglée                             | Convention d'INFRA-01 et INFRA-02, arbitrage inverse : c'est ici la **dernière** image publiée, sur Docker Hub comme sur quay.io — MinIO n'y publie plus depuis septembre 2025. Le correctif de CVE-2025-62506 (octobre 2025) n'existe qu'en binaire ; il vise les comptes de service à politique restreinte, qu'une instance à compte racine unique n'utilise pas.                       |
| Console réduite au navigateur d'objets                              | `RELEASE.2025-05-24T17-08-30Z` a retiré les écrans d'administration de l'édition communautaire. Le ticket demande de documenter l'URL et les identifiants de développement : c'est fait, en disant ce qu'on y trouve réellement plutôt qu'en promettant une console complète.                                                                                                             |
| Sonde `/minio/health/live` conservée, en `curl`                     | Les exemples officiels de MinIO ont basculé sur `mc ready local` parce que `curl` avait disparu de l'image fin 2023. Il est **revenu** : vérifié dans le tag épinglé avant d'écrire la ligne, ce qui permet de garder l'endpoint que demande le ticket. À revérifier à tout changement de tag — sans `curl`, la sonde échouerait en boucle et INFRA-04 attendrait un service jamais sain. |
| `mc anonymous set none` écrit alors que c'est déjà le défaut        | Le ticket dit « applique la policy voulue ». La policy voulue est l'absence d'accès anonyme, puisque BACK-13 passe par des URLs pré-signées. L'écrire referme au démarrage suivant un bucket qu'on aurait ouvert depuis la console.                                                                                                                                                       |
| Alias `mc` nommé `juui` et non `local`                              | `local` existe déjà dans la configuration par défaut de `mc`, avec le couple `minioadmin/minioadmin`. Le réutiliser donne un « Access Denied » à la création du bucket, sans rapport visible avec sa cause.                                                                                                                                                                               |
| `restart: 'no'` explicite sur `minio-init`                          | C'est déjà le défaut de Compose, mais les quatre services précédents portent tous `unless-stopped` : recopié par réflexe, il relancerait sans fin un conteneur dont le travail **est** de se terminer.                                                                                                                                                                                    |
| `MINIO_SITE_REGION` ajoutée au service                              | Sans elle, `S3_REGION` ne décrirait que le client, le serveur acceptant n'importe quelle région annoncée. Même raisonnement que le `PGPORT` d'INFRA-01 : une variable doit décrire ce qu'elle prétend décrire.                                                                                                                                                                            |
| Script versionné dans `docker/minio/` plutôt qu'`entrypoint` inline | Le ticket place l'amorçage dans `docker/minio/`, et c'est le raisonnement du `redis.conf` d'INFRA-02 : l'essentiel de ces trois commandes tient dans leurs raisons, qu'un fichier peut porter.                                                                                                                                                                                            |
| Ports publiés sur toutes les interfaces                             | Contrairement à Redis et RedisInsight, MinIO réclame des identifiants et sa console a une page de connexion. La règle du dépôt tient en une phrase : service sans authentification → boucle locale.                                                                                                                                                                                       |
| Correction de ce que SETUP-05 disait des identifiants racine        | Le README et `.env.example` affirmaient que MinIO, comme PostgreSQL, ne les lit qu'à la première création de son volume. Vérifié : ils sont relus à **chaque** démarrage, les anciens sont refusés aussitôt et les données restent. Le vrai piège est ailleurs — les clés d'accès créées sous l'ancien compte racine deviennent inaccessibles.                                            |

## Conventions

- Fins de ligne LF, UTF-8, indentation à 2 espaces (4 pour Python) : voir
  [`.editorconfig`](.editorconfig).
- `main` est la branche de référence ; toute modification passe par une branche
  dédiée puis une pull request.

### Style de code

Point-virgule final, guillemets simples, virgule finale partout, largeur de ligne
à 100 caractères. La configuration fait foi — personne n'a à retenir cette liste :

```bash
pnpm format && pnpm lint
```

Plus besoin d'y penser avant un commit : le [hook de
pre-commit](#hooks-de-pre-commit) applique ces deux passes aux fichiers indexés.
Ces commandes restent utiles pour reformater le dépôt d'un coup, après un
changement de configuration par exemple.

Prettier ne remet jamais la prose à la ligne (`proseWrap: 'preserve'`) : les
paragraphes du Markdown restent découpés à la main. Il réaligne en revanche les
tableaux, ce qui allonge leurs lignes source.

### Configurations partagées

| Package                                                 | Rôle                                                                                  |
| ------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| [`@repo/eslint-config`](packages/config-eslint)         | Presets ESLint : `base`, `react`, `next`.                                             |
| [`@repo/prettier-config`](packages/config-prettier)     | Configuration Prettier, ré-exportée par [`prettier.config.mjs`](prettier.config.mjs). |
| [`@repo/typescript-config`](packages/config-typescript) | Trois `tsconfig` : `base.json`, `react-library.json`, `nextjs.json`.                  |
| [`@repo/tailwind-config`](packages/config-tailwind)     | Le thème Tailwind v4 du dépôt, et la chaîne PostCSS.                                  |

Les trois presets ESLint forment une chaîne — `next` étend `react`, qui étend
`base` — et partagent donc exactement le même socle de règles :

- **`base`** — TypeScript et Node, sans rien de spécifique à React. Pour
  `packages/*` et les scripts d'outillage.
- **`react`** — `base` plus les règles des hooks. Pour `packages/ui` (SHARED-01),
  qui est du React sans Next.
- **`next`** — `react` plus les 22 règles de `@next/eslint-plugin-next`. Pour les
  trois applications (FRONT-01 et suivants).

Une application les consomme ainsi :

```js
// frontend/frontend-professional/eslint.config.mjs
import next from '@repo/eslint-config/next';
import { defineConfig, globalIgnores } from 'eslint/config';

export default defineConfig([globalIgnores(['.next/**']), ...next]);
```

La ré-exclusion locale de `.next/` n'est pas redondante avec celle de la racine :
la recherche de configuration partant du fichier analysé, ce fichier **remplace**
celui de la racine pour son workspace — ses exclusions comprises.

Le socle de règles se modifie en un seul endroit :
[`packages/config-eslint/rules.js`](packages/config-eslint/rules.js).

Le preset `base` y branche aussi le **résolveur d'imports** — la variante
TypeScript, seule à lire les `paths` des `tsconfig` et la carte `exports` des
packages du dépôt. C'est ce qui donne leur objet à `import-x/no-unresolved` et
`import-x/no-cycle` : sans résolveur, ces deux règles ne signalent jamais rien.
Les motifs qu'il reçoit suivent [`pnpm-workspace.yaml`](pnpm-workspace.yaml) et
sont ancrés sur la racine du dépôt, pour qu'un lint lancé depuis un sous-dossier
trouve les mêmes `tsconfig`.

#### `@repo/typescript-config`

Même principe, une chaîne : `react-library.json` et `nextjs.json` étendent tous
deux `base.json`.

| Fichier              | Pour qui                                     | Ce qu'il ajoute                                                                                                                                                                   |
| -------------------- | -------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `base.json`          | personne directement                         | Le socle : cible ES2023, résolution `bundler`, et le mode strict complet — `strict`, `noUncheckedIndexedAccess`, `noImplicitOverride`, `verbatimModuleSyntax`, `isolatedModules`. |
| `react-library.json` | `packages/ui`                                | `jsx: react-jsx` et les bibliothèques `DOM`.                                                                                                                                      |
| `nextjs.json`        | les trois applications (FRONT-01 à FRONT-03) | `jsx: preserve` — le JSX est laissé à SWC —, le plugin d'éditeur `next`, `allowJs` et `incremental`.                                                                              |

Un consommateur se réduit à ceci :

```json
// packages/ui/tsconfig.json
{
  "extends": "@repo/typescript-config/react-library.json",
  "compilerOptions": { "paths": { "@repo/ui/*": ["./src/*"] } },
  "include": ["src/**/*.ts", "src/**/*.tsx"],
  "exclude": ["node_modules", "dist"]
}
```

**`include`, `exclude` et `paths` restent chez lui**, et ce n'est pas un oubli :
TypeScript résout les chemins relatifs d'un `tsconfig` _relativement au fichier
de configuration dont ils proviennent_. Un `include` posé dans `base.json`
désignerait `packages/config-typescript`, jamais le projet qui hérite.

#### `@repo/tailwind-config`

Tailwind v4 n'a plus de `tailwind.config.js`, donc plus de preset au sens de la
v3 : un thème partagé **est** un fichier CSS que l'on importe.
[`packages/config-tailwind/theme.css`](packages/config-tailwind/theme.css) tient
ce rôle et porte tout — palette claire et sombre, échelle de rayons,
typographie, variante `.dark`. C'est le seul fichier du dépôt où une couleur est
écrite ; en changer une y repeint les trois applications et `@repo/ui`.

Une application n'y touche jamais : elle importe `@repo/ui/globals.css`, qui
n'est qu'un renvoi vers ce fichier.

La ligne à ne pas perdre de vue :

```css
@source '../ui/src/**/*.{ts,tsx}';
```

C'est le `content` d'autrefois. Tailwind ignore `node_modules` dans sa détection
automatique — et c'est précisément par un lien symbolique de `node_modules`
qu'une application atteint `@repo/ui`. Sans cette ligne, **toutes** les classes
des composants seraient purgées du CSS final. Le chemin est résolu relativement
à `theme.css`, d'où `../ui/src`.

La chaîne PostCSS vit dans le même package ; les trois applications la
ré-exportent au lieu de la réécrire :

```js
// frontend/frontend-professional/postcss.config.mjs
export { default } from '@repo/tailwind-config/postcss.config';
```

Enfin, la typographie est un **contrat**, pas une police : le preset déclare
`--font-sans: var(--font-juui-sans, …)`, à charge pour chaque application
d'alimenter `--font-juui-sans` avec `next/font`. `frontend-professional` y charge
Geist depuis FRONT-01, en sans et en mono ; une application qui ne le ferait pas
retomberait sur la valeur de repli, sans rien casser.

### Bibliothèque de composants (`@repo/ui`)

[`packages/ui`](packages/ui) porte les composants, le thème et les utilitaires
partagés par les trois frontends. Le package n'est **jamais compilé** : il
s'exporte en source TypeScript, et chaque application le transpile.

| Chemin                   | Contenu                                                                           |
| ------------------------ | --------------------------------------------------------------------------------- |
| `src/components/`        | Composants shadcn/ui, `theme-provider.tsx`, `theme-toggle.tsx`, `data-table.tsx`. |
| `src/hooks/`             | Hooks partagés — `use-mobile.ts`, dont dépend la barre latérale.                  |
| `src/lib/utils.ts`       | `cn()` — fusion de classes Tailwind avec résolution des conflits.                 |
| `src/styles/globals.css` | Renvoi vers le thème partagé — le fichier qu'importe une application.             |
| `components.json`        | Configuration de la CLI shadcn en mode monorepo.                                  |

Les imports passent par la carte `exports` du package, jamais par un chemin
relatif :

```ts
import { Button } from '@repo/ui/components/button';
import { ThemeProvider } from '@repo/ui/components/theme-provider';
import { cn } from '@repo/ui/lib/utils';
```

#### Identité visuelle

shadcn décrit un thème par quatre dimensions indépendantes. Celles de Juui :

| Dimension          | Valeur    | Où elle est inscrite                                      |
| ------------------ | --------- | --------------------------------------------------------- |
| Base de primitives | `radix`   | `components.json` — `"style": "radix-vega"`               |
| Style              | `vega`    | idem                                                      |
| Couleur de base    | `mist`    | `components.json` — `"baseColor": "mist"`, et `theme.css` |
| Couleur d'accent   | `emerald` | `theme.css` — `--primary`, `--ring`, `--sidebar-primary`  |

`pnpm dlx shadcn@4.19.0 info -c packages/ui` relit ces quatre valeurs depuis le
dépôt et doit répondre `vega` / `mist` / `emerald` — c'est le contrôle à faire
après toute retouche du thème.

Toutes les couleurs sont des variables CSS définies **une seule fois**, dans
[`packages/config-tailwind/theme.css`](packages/config-tailwind/theme.css).
Changer `--primary` y suffit à repeindre les trois applications ; aucune ne
redéfinit de couleur chez elle.

Le mode sombre est piloté par la classe `.dark` sur `<html>`, posée par le
`ThemeProvider` du package. Rien ne dépend de `prefers-color-scheme` : c'est ce
qui permet à l'utilisateur de choisir un thème indépendamment de son système.

#### Ajouter un composant

Depuis la racine du dépôt, `-c packages/ui` désignant le workspace cible :

```bash
pnpm dlx shadcn@4.19.0 add tooltip -c packages/ui
```

Le fichier atterrit dans `packages/ui/src/components/`, ses imports réécrits en
`@repo/ui/...` grâce aux alias de `components.json`. Les variables de thème que
le registre apporte, elles, vont dans `packages/config-tailwind/theme.css` :
`components.json` désigne le preset, pas le `globals.css` du package — sans quoi
le thème recommencerait à se disperser. Le registre livre en guillemets doubles
et sans point-virgule : enchaîner systématiquement

```bash
pnpm format && pnpm lint:fix
```

**Épingler la version de la CLI** (`shadcn@4.19.0`) plutôt que `@latest` : une
version plus récente pourrait servir un autre style que `radix-vega` et faire
diverger le socle.

Le socle installé couvre Button, Input, Label, Card, Dialog, DropdownMenu,
Select, Sonner (notifications), Field (primitives de formulaire), Table, Badge,
Skeleton — plus Separator, tiré par Field. FRONT-03 y a ajouté Sidebar et
Breadcrumb, les deux primitives d'un back-office, avec ce que Sidebar réclame :
Sheet (son volet mobile), Tooltip (ses info-bulles une fois repliée) et le hook
`use-mobile`.

S'y ajoutent trois composants maison, absents du registre shadcn :
`theme-provider.tsx`, qui pose la classe `.dark`, `theme-toggle.tsx`, le bouton
qui la commande, et `data-table.tsx`, décrit juste après. Le deuxième a d'abord
vécu dans `frontend-professional` (FRONT-01) ; FRONT-02 l'a remonté ici plutôt
que de le recopier dans une deuxième application — c'est la règle que pose le
ticket, et la raison d'être du package.

##### `DataTable` — la table de données

FRONT-03 demandait de **vérifier** que le composant `Table` couvrait le tri, le
filtrage et la pagination, et de créer une extension dans le package partagé
dans le cas contraire. Il ne les couvre pas : `table.tsx` est purement
présentationnel — huit composants qui habillent `<table>`, `<thead>`, `<tr>`,
sans le moindre état. Le registre shadcn n'a rien à proposer non plus, sa page
`data-table` étant un **guide** qui assemble ce même `table.tsx` avec TanStack
Table, et non un composant téléchargeable.

D'où [`data-table.tsx`](packages/ui/src/components/data-table.tsx) : `Table`
plus [TanStack Table](https://tanstack.com/table), avec tri par colonne
(`aria-sort` sur la cellule d'en-tête), filtre texte sur une colonne désignée et
pagination. L'appelant décrit ses colonnes, rien d'autre — l'état reste dans la
table :

```tsx
const column = createDataTableColumnHelper<Clinique>();
const columns = column.columns([column.accessor('nom', { header: 'Clinique' })]);

<DataTable columns={columns} data={CLINIQUES} filterColumnId="nom" pageSize={5} />;
```

**TanStack Table est en version 9, une réécriture** : les exemples que l'on
trouve en ligne, guide shadcn compris, sont écrits pour la 8 et ne fonctionnent
pas ici. Le hook s'appelle `useTable` et non `useReactTable`, les capacités
s'enregistrent dans un `tableFeatures` au lieu des options `getSortedRowModel()`,
et une cellule se rend avec `<table.FlexRender cell={…} />`. Le paquet embarque
ses propres consignes à jour, à lire plutôt que le web :

```bash
npx @tanstack/intent@latest list
```

Deux pièges tiennent au même mécanisme, l'enregistrement explicite. **Une
capacité non enregistrée n'existe pas** : sans `rowPaginationFeature`, il n'y a
ni état `pagination` ni méthode `setPageIndex`. Et **les fonctions de tri et de
filtrage ne sont pas globales** : une colonne en mode `auto` — le défaut —
résout un nom (`text`, `includesString`) dans les registres `sortFns` et
`filterFns`, qu'il faut déclarer. L'oubli ne casse pas de la même façon des deux
côtés, ce qui le rend pénible à diagnostiquer : le tri se rabat sur une
comparaison générique et **paraît** fonctionner, tandis que le filtre ne trouve
aucune fonction et laisse passer toutes les lignes — un champ de recherche qui
ne filtre rien, sans la moindre erreur. Les deux cas se signalent en console, en
développement seulement.

#### Vérifier le thème sans lancer d'application

Une retouche du thème se contrôle sans démarrer quoi que ce soit, en le
compilant :

```bash
pnpm --filter @repo/ui run check:css
```

La sortie `packages/ui/dist/globals.built.css` (non versionnée) doit contenir
le bloc `:root`, le bloc `.dark`, et les classes utilisées par les composants du
package — signe que la directive `@source` fait bien son travail. Depuis
SHARED-02 la preuve est plus forte qu'elle n'en a l'air : le thème est atteint
**par le lien symbolique pnpm** de `node_modules`, exactement comme le fait
`frontend-professional`.

Le pendant du côté TypeScript, qui vérifie du même coup que l'héritage des
configurations partagées se résout :

```bash
pnpm typecheck
```

#### Ce que fait une application (FRONT-01 à FRONT-03)

Les trois existent : [`frontend-professional`](frontend/frontend-professional)
(FRONT-01), [`frontend-individual`](frontend/frontend-individual) (FRONT-02) et
[`frontend-admin`](frontend/frontend-admin) (FRONT-03). La première sert de
**patron**, et les deux suivantes ont repris ces sept points à l'identique sans
en amender aucun. Seuls les distinguent leur port, leurs métadonnées, et ce que
décrivent les deux sections suivantes — le volet SEO de la seule application
publique, et le back-office de la seule qui soit entièrement privée.

1. Quatre dépendances de workspace — `@repo/ui`, `@repo/tailwind-config`,
   `@repo/typescript-config` et `@repo/eslint-config`, toutes en `"workspace:*"`
   — et `transpilePackages: ['@repo/ui']` dans
   [`next.config.ts`](frontend/frontend-professional/next.config.ts), le package
   étant livré en TypeScript non compilé.
2. `export { default } from '@repo/tailwind-config/postcss.config';` dans son
   [`postcss.config.mjs`](frontend/frontend-professional/postcss.config.mjs).
3. Un [`app/globals.css`](frontend/frontend-professional/app/globals.css) à elle,
   qui ré-importe celui de `@repo/ui` et déclare ses propres sources — la
   détection automatique de Tailwind part du fichier qui porte
   `@import 'tailwindcss'`, lequel vit dans `packages/config-tailwind` :

   ```css
   @import '@repo/ui/globals.css';

   @source '../app/**/*.{ts,tsx}';
   @source '../components/**/*.{ts,tsx}';
   ```

   C'est ce fichier-là, et non celui du package, que `app/layout.tsx` importe.

4. `<html lang="fr" suppressHydrationWarning>` et `<ThemeProvider>` autour de
   l'arbre — sans `suppressHydrationWarning`, next-themes provoque un
   avertissement d'hydratation à chaque rendu.
5. Une police chargée avec `next/font` et exposée en `--font-juui-sans` sur
   `<html>` : c'est la variable que lit le `--font-sans` du preset. La classe
   `font-sans` doit en outre être posée sur `<body>` — le thème définit le token,
   il ne l'applique à aucun élément.
6. Un [`tsconfig.json`](frontend/frontend-professional/tsconfig.json) qui étend
   `@repo/typescript-config/nextjs.json` et déclare chez lui ce qu'un fichier
   partagé ne peut pas porter — ses `paths` (`@/*` et
   `"@repo/ui/*": ["../../packages/ui/src/*"]`), son `include` et son `exclude`.
7. `output: 'standalone'` **et** un `outputFileTracingRoot` pointant la racine du
   dépôt. Le second n'est pas facultatif dans un monorepo : sans lui, le traçage
   part du dossier de l'application et n'embarque pas les dépendances atteintes
   par les liens symboliques pnpm. La sortie se construit alors sans erreur et
   échoue au démarrage.

Ni `src/`, ni `tailwind.config.ts`, ni `prettier.config.mjs` local : le code
applicatif vit dans `app/` et `components/`, le thème est du CSS depuis
Tailwind v4, et une configuration Prettier locale devrait redéfinir son
`tailwindStylesheet` sous peine de trier les classes sans le thème.

#### Le volet SEO de `frontend-individual`

Des trois applications, `frontend-individual` est la seule à être **publique**
et destinée à l'indexation — les deux autres sont des espaces authentifiés.
C'est la seule différence de fond avec le patron, et elle tient dans quatre
fichiers de `app/` :

| Fichier       | Rôle                                                                                                                       |
| ------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `site-url.ts` | L'URL canonique du site, lue une fois dans `SITE_URL`. Les trois autres s'y réfèrent au lieu d'en garder chacun une copie. |
| `robots.ts`   | Sert `/robots.txt` : indexation autorisée, et renvoi vers le sitemap.                                                      |
| `sitemap.ts`  | Sert `/sitemap.xml` : les pages publiques — l'accueil pour l'instant.                                                      |
| `layout.tsx`  | `metadataBase`, balise canonique, Open Graph, carte Twitter, directives `robots` et `googlebot`.                           |

Rien n'est routé à la main : dans l'App Router, `robots.ts` et `sitemap.ts` sont
des **fichiers de métadonnées** — leur nom suffit à servir la route qui leur
correspond.

**Tout est produit au build.** La page d'accueil n'appelle aucune API dynamique,
Next la prérend donc, comme les deux fichiers de métadonnées. `pnpm build` le
dit lui-même, `○` valant « prerendered as static content » :

```text
Route (app)
┌ ○ /
├ ○ /_not-found
├ ○ /robots.txt
└ ○ /sitemap.xml
```

C'est la génération statique que demande le ticket, obtenue sans rien forcer :
aucun `export const dynamic = 'force-static'` n'est écrit nulle part. Le jour où
une page aura besoin d'un rendu par requête, elle le déclarera pour elle seule —
et cette ligne-là méritera qu'on la remarque.

**Ce qu'il faut en retenir** : `SITE_URL` est figée au moment du build, comme
toute variable qui entre dans un rendu statique. La laisser à sa valeur de
développement en production donnerait un `sitemap.xml` rempli d'URLs `localhost`,
sans la moindre erreur au démarrage. Elle se déclare dans le
[`.env.local.example`](frontend/frontend-individual/.env.local.example) de
l'application sur le poste, et se passera en `build.args` en conteneur
(INFRA-05), où le `.env` de la racine la porte sous le nom
`FRONTEND_INDIVIDUAL_SITE_URL`.

Ce qui n'y est **pas**, et pourquoi : ni image Open Graph (`opengraph-image`) ni
manifest — les deux réclament des visuels que le dépôt n'a pas encore, et une
carte de partage qui annonce une image absente est moins bonne qu'une carte
sobre ; pas de `lastModified` dans le sitemap non plus — la seule date
disponible aujourd'hui serait celle du build, qui changerait à chaque
déploiement sans que la page ait bougé. Annoncer une modification qui n'a pas eu
lieu est un signal que les moteurs finissent par ignorer.

#### Le back-office de `frontend-admin`

À l'exact opposé de la précédente, `frontend-admin` est la seule des trois à être
**entièrement privée**. Elle applique le patron sans y toucher, et y ajoute
quatre choses.

**Rien n'est accessible sans session.** La règle est inversée par rapport à un
site ordinaire : ce n'est pas le contenu protégé qui se déclare, c'est le
contenu public, et il se réduit à la page de connexion.
[`proxy.ts`](frontend/frontend-admin/proxy.ts) redirige toute autre adresse vers
`/login`, en conservant celle qui était demandée dans un paramètre `next`.

> **`proxy.ts`, et non `middleware.ts`.** Next 16 a renommé la convention.
> L'ancien nom fonctionne encore mais fait avertir **chaque build** — le genre de
> bruit permanent que FRONT-01 a refusé en désactivant `agentRules`. La fonction
> exportée s'appelle donc `proxy` : c'est `mod.proxy` que Next cherche dans ce
> fichier, et un export nommé `middleware` échouerait.

Son `matcher` exclut quatre chemins. `login` d'abord, sans quoi la redirection se
redirigerait elle-même. **`robots.txt` ensuite, et c'est moins évident** : ce
fichier doit être servi, car un robot redirigé vers une page de connexion n'y
lit aucune directive — l'interdiction ci-dessous aurait été écrite pour
personne. Les fichiers statiques et les images optimisées ferment la liste : les
faire transiter coûterait une exécution par requête, pour rien.

**Aucune indexation.** Le bloc `robots` de
[`app/layout.tsx`](frontend/frontend-admin/app/layout.tsx) est l'inverse de celui
de `frontend-individual`, au même endroit et dans le même ordre : comparer les
deux fichiers doit suffire à voir laquelle des applications est publique. S'y
ajoutent `nocache` et `noarchive`, qui interdisent de **conserver** une copie —
une page de back-office en cache public survivrait à sa dépublication. Et
[`app/robots.ts`](frontend/frontend-admin/app/robots.ts) sert un `Disallow: /`
complet, sans sitemap. Ces balises ne protègent rien : elles s'adressent aux
robots qui les respectent. Ce qui protège, c'est le proxy et, en dernier
ressort, l'API. Elles évitent l'accident, pas l'attaque.

**Aucun rendu statique.** `export const dynamic = 'force-dynamic'` dans
[`app/(protected)/layout.tsx`](<frontend/frontend-admin/app/(protected)/layout.tsx>),
et là seulement — c'est la **seule** directive de ce genre du dépôt, et la
section précédente explique pourquoi sa valeur tient à sa rareté. Elle est
presque redondante, la lecture d'un cookie suffisant déjà à rendre le segment
dynamique ; elle est écrite quand même, pour qu'aucune page de back-office ne
finisse en HTML prérendu le jour où l'une d'elles n'aura besoin d'aucune donnée
de session. La page de connexion, hors de ce groupe, ne la porte pas : elle
n'affiche rien de confidentiel.

**Un shell de back-office.** Les groupes de routes découpent l'application en
deux : `(auth)` pour la connexion, nue, et `(protected)` pour tout le reste,
sous une barre latérale repliable, un fil d'Ariane et une zone de contenu.

| Fichier                           | Rôle                                                                                                          |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `lib/session.ts`                  | Nom du cookie, type `Role`, lecture de la session. **Sans `next/headers`** : le proxy tourne en runtime Edge. |
| `lib/require-role.ts`             | `getSession()` et la garde `requireRole('admin')` qu'appelle le layout protégé.                               |
| `components/navigation.ts`        | Les sections du back-office, déclarées **une seule fois**.                                                    |
| `components/admin-sidebar.tsx`    | La navigation latérale, ses entrées filtrées par rôle.                                                        |
| `components/admin-breadcrumb.tsx` | Le fil d'Ariane, dérivé du chemin.                                                                            |

Le fil d'Ariane n'est jamais renseigné page par page : il se déduit de
`usePathname()` et tire ses libellés de la même liste que la barre latérale.
Une page qui déclarerait elle-même sa position finirait par mentir après un
déplacement de route, et deux listes de libellés divergeraient au premier
renommage.

**Le contrôle d'accès par rôle est un confort d'affichage**, et le code le dit à
l'endroit où l'on serait tenté de croire l'inverse. Il évite d'afficher un écran
à qui n'a rien à y faire ; il ne protège aucune donnée. La vérification qui fait
foi est celle du backend — la fabrique `require_role(...)` de BACK-10, du côté où
la réponse est produite.

**Ce qui reste à FRONT-07.** Rien ici ne vérifie un jeton : `sessionFromToken`
constate la présence du cookie, sans lire sa signature ni son expiration. Le
service JWT est l'objet de BACK-10, son pendant navigateur celui de FRONT-07 —
qui déclare posséder `middleware.ts` et `app/(auth)/login/page.tsx`. Les chemins
posés ici sont donc les siens au caractère près, à la nuance de nom près
expliquée plus haut : il aura une fonction à compléter, pas une application à
re-router. La page de connexion n'a d'ailleurs pas de formulaire — en écrire un
sans API derrière aurait produit du code à jeter et un écran qui ment sur ce
qu'il sait faire.

##### Voir le back-office aujourd'hui

Puisque rien n'émet encore de session, toute adresse redirige vers `/login`.
Pour traverser, poser le cookie à la main — sa **présence** suffit, sa valeur
n'est pas lue :

1. ouvrir <http://localhost:3003> et attendre la page de connexion ;
2. dans les outils de développement, onglet **Application** (ou **Stockage**),
   section **Cookies**, ajouter sur `http://localhost:3003` un cookie nommé
   `juui_session`, valeur quelconque, chemin `/` ;
3. recharger.

Ou, plus court, depuis la console du navigateur :

```js
document.cookie = 'juui_session=demo; path=/';
```

Cette porte se referme d'elle-même avec FRONT-07, qui remplacera la lecture du
cookie par une vérification du jeton.

### Écarts assumés avec le ticket SHARED-01

| Écart                                                             | Raison                                                                                                                                                                                                                                                                |
| ----------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Critère « les 3 applications affichent un composant » non vérifié | `frontend/*` ne contient encore que des `.gitkeep` : FRONT-01 à FRONT-03 restent à faire. Le contrat qu'elles devront honorer est décrit ci-dessus, et ce qui était vérifiable ici l'a été — typage, lint, et compilation réelle du thème.                            |
| `sonner` à la place du composant `toast`                          | Le registre shadcn n'expose plus de `toast` pour la base `radix` ; `sonner` est son composant de notification. `toast` n'existe que pour la base Base UI.                                                                                                             |
| `field` à la place du composant `form`                            | L'entrée `form` du registre est devenue un stub sans fichier. L'ancien `form.tsx` était soudé à react-hook-form, que FRONT-05 remplace par TanStack Form. `field` fournit les mêmes primitives — label, description, message d'erreur — sans imposer de bibliothèque. |
| `ThemeProvider` ajouté au périmètre                               | Le ticket ne demandait que les variables. Sans le fournisseur qui pose la classe `.dark`, chaque application recâblerait next-themes de son côté et les trois finiraient par diverger — l'inverse de l'objectif du package.                                           |
| Accent `emerald` écrit à la main dans `globals.css`               | La CLI shadcn sait poser une couleur de base, pas une couleur d'accent : seul le générateur web `ui.shadcn.com/create` le fait. Les valeurs employées restent celles du registre au caractère près, ce que confirme `shadcn info`.                                    |
| Pas de preset Tailwind partagé                                    | Tailwind v4 n'a plus de fichier de configuration JavaScript : le thème **est** `globals.css`, et le `content` d'autrefois s'écrit `@source`. SHARED-02 devra en tenir compte pour `packages/config-tailwind`.                                                         |
| `@tailwindcss/cli` en dépendance de développement                 | Ni le ticket ni le build ne le réclament, mais c'est le seul moyen de prouver que le thème compile tant qu'aucune application n'existe.                                                                                                                               |
| `shadcn` et `tw-animate-css` en `dependencies`                    | Le registre les place en `devDependencies`. Ce sont des `@import` de `globals.css`, donc nécessaires au **build des applications** : en devDependencies, un `pnpm install --prod` en image Docker (INFRA-05) casserait la compilation CSS.                            |

### Écarts assumés avec le ticket SHARED-02

| Écart                                                              | Raison                                                                                                                                                                                                                                                                   |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `@repo/typescript-config` et `@repo/tailwind-config`               | Le ticket écrivait `@repo/config-typescript`. Les deux packages du même genre déjà en place s'appellent `@repo/eslint-config` et `@repo/prettier-config` : une seule convention de nommage vaut mieux que la fidélité littérale. Les dossiers, eux, sont ceux du ticket. |
| Pas de preset Tailwind au sens de la v3                            | Tailwind v4 n'a plus de configuration JavaScript. Le preset est `theme.css`, un fichier importé — le mécanisme que Tailwind documente lui-même pour partager un thème entre projets.                                                                                     |
| `content: ['../../packages/ui/src/**']` → `@source '../ui/src/**'` | Même directive, syntaxe v4, et surtout autre point d'origine : `@source` est résolu relativement à la feuille de style qui le porte, ici `packages/config-tailwind/theme.css`.                                                                                           |
| `postcss.config.mjs` déplacé hors de `packages/ui`                 | Revient sur un choix de SHARED-01. La chaîne PostCSS est de l'outillage Tailwind : la laisser ailleurs que le thème obligeait les applications à connaître deux packages pour une seule préoccupation. Aucune n'existant encore, rien à casser.                          |
| `components.json` pointe sur `theme.css`, hors du package          | Sans cela, `shadcn add` écrirait ses variables de thème dans le `globals.css` de `@repo/ui` et le thème se remettrait à diverger. `shadcn info` continue de répondre `vega` / `mist` / `emerald`, ce qui le vérifie.                                                     |
| Variables de typographie ajoutées au périmètre                     | Le ticket demande que le preset porte « la typographie ». Il ne peut pas porter la police elle-même — c'est `next/font`, donc l'application. Le preset porte donc le contrat : `--font-sans` lit `--font-juui-sans`, avec repli.                                         |
| Dépendances Tailwind en `dependencies`                             | `tailwindcss`, `@tailwindcss/postcss`, `tw-animate-css` et `shadcn` sont nécessaires au **build** des applications. En `devDependencies`, un `pnpm install --prod` en image Docker (INFRA-05) casserait la compilation CSS — même raisonnement qu'en SHARED-01.          |
| Critère « une modification du preset se répercute sur les 3 apps » | `frontend/*` ne contient encore que des `.gitkeep`. Ce qui était vérifiable l'a été : changer `--primary` dans le preset change bien le CSS compilé de `@repo/ui`, atteint par le même lien symbolique que celui qu'emprunteront les applications.                       |
| `nextjs.json` livré sans consommateur                              | FRONT-01 à FRONT-03 en dépendent ; le poser maintenant est précisément ce qui garantit que les trois applications démarreront identiques.                                                                                                                                |

### Écarts assumés avec le ticket FRONT-01

| Écart                                                               | Raison                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| ------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Pas de `tailwind.config.ts`                                         | Le ticket demande un fichier qui n'existe plus : Tailwind v4 n'a pas de configuration JavaScript. Le thème **est** le CSS partagé, et le `content` d'autrefois s'écrit `@source` — arbitrage déjà rendu en SHARED-02.                                                                                                                                                                                                                                                  |
| `@repo/api-client` absent des dépendances et de `transpilePackages` | Le package est l'objet de SHARED-03 et n'existe pas : une dépendance `workspace:*` vers un package inexistant fait échouer `pnpm install`. Les deux lignes reviendront au ticket qui le crée.                                                                                                                                                                                                                                                                          |
| `@repo/typescript-config` et `@repo/tailwind-config`                | Le ticket écrit `@repo/config-typescript` et `@repo/config-tailwind`. Ce sont les noms des dossiers, pas ceux des packages — même écart qu'en SHARED-02.                                                                                                                                                                                                                                                                                                               |
| `outputFileTracingRoot` ajouté à `next.config.ts`                   | Non demandé. Sans lui la sortie `standalone` est tracée depuis le dossier de l'application et n'embarque pas les dépendances atteintes par les liens symboliques pnpm : elle se construit sans erreur puis échoue au démarrage, ce qui rendrait le critère d'acceptation faux tout en le laissant passer.                                                                                                                                                              |
| `agentRules: false`                                                 | Next 16 dépose de lui-même un `AGENTS.md` et un `CLAUDE.md` dans l'application à chaque `next dev`. Le dépôt n'a aucun fichier de ce genre ; les garder imposerait soit une modification non commitée en permanence, soit de la prose générée à relire à chaque PR. La documentation du dépôt reste ce README et `documentation/`.                                                                                                                                     |
| Deux renvois de SETUP-03 levés, deux conservés                      | `REACT_VERSION` est figée — les applications épinglent react 19.2.8 — et le résolveur TypeScript est posé, ce qui active `import-x/no-unresolved` et `import-x/no-cycle`. En revanche `tseslint.configs.recommendedTypeChecked` et `eslint-plugin-jsx-a11y` restent hors du socle : le premier change le coût de chaque `pnpm lint` et mérite sa propre mesure, le second est un vrai sujet que le commentaire d'origine rattache au parcours de prise de rendez-vous. |
| Réordonnancement des imports `@repo/*`                              | Effet du résolveur, pas une préférence : sans lui `@repo/eslint-config/base` était classé comme un paquet externe, et le `pathGroups` de `rules.js` qui le range en « interne » restait sans effet. Un seul fichier du dépôt était concerné, [`eslint.config.mjs`](eslint.config.mjs), corrigé automatiquement.                                                                                                                                                        |
| `typescript@6.0.3`, et non le motif d'alias TypeScript 7            | SETUP-03 renvoyait ce choix ici. TypeScript 7 est bien la version `latest` sur npm, mais ne livre toujours pas d'API compilateur — annoncée pour la 7.1, encore en pré-publication — ce qui bloque typescript-eslint ; et le paquet `@typescript/typescript6` que le motif utilise plafonne à 6.0.2, une version derrière celle du dépôt. L'adopter aujourd'hui désalignerait le dépôt pour un gain nul.                                                               |
| `lucide-react` déclarée par l'application                           | `@repo/ui` la porte déjà, mais le `node_modules` strict de pnpm interdit d'importer ce qu'on ne déclare pas — et la bascule de thème utilise ses icônes directement. Même version que le package, pour que pnpm n'en installe qu'une.                                                                                                                                                                                                                                  |
| Page d'accueil plus fournie que « minimale »                        | Le ticket demande d'afficher un composant. Un bouton seul prouve la transpilation, mais ni le thème sombre, ni la police, ni la non-purge des classes de l'application. Chaque élément de la page atteste un maillon précis, et sa disparition désignerait la pièce cassée.                                                                                                                                                                                            |
| Textes d'interface accentués                                        | Le reste du dépôt écrit son français sans accents hors des `.md`. La règle ne peut pas s'étendre à ce qui s'affiche : « cliniques veterinaires » sur l'écran d'un cabinet serait une faute, pas une convention. Commentaires et messages de commit restent sans accents.                                                                                                                                                                                               |

> **Note.** Les deux critères que SHARED-01 et SHARED-02 avaient dû laisser en
> suspens faute d'application — « les trois applications affichent un composant »
> et « une modification du preset se répercute visuellement » — sont désormais
> vérifiables, et vérifiés sur `frontend-professional`. Les deux tableaux
> précédents gardent leur rédaction d'origine : ils décrivent l'état du dépôt au
> moment de leur ticket, pas celui d'aujourd'hui.

### Écarts assumés avec le ticket FRONT-02

| Écart                                                                      | Raison                                                                                                                                                                                                                                                                                                                            |
| -------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ThemeToggle` remonté dans `@repo/ui`, et `frontend-professional` retouché | Le ticket l'impose : « tout élément visuel commun doit vivre dans `@repo/ui` », et la bascule de thème est le premier composant que deux applications se partagent. Une application déjà livrée est donc modifiée par le ticket d'une autre — c'est le prix de la règle, et il valait mieux le payer sur une copie que sur trois. |
| `lucide-react` retiré de `frontend-professional`                           | Conséquence de la ligne précédente : l'application n'importe plus aucune icône directement, seul `@repo/ui` le fait. La ligne du tableau FRONT-01 qui justifiait cette dépendance n'est pas corrigée — elle décrivait l'état du dépôt à sa date.                                                                                  |
| Un `.gitkeep` dans les `components/` des deux applications                 | Chaque `app/globals.css` porte `@source '../components/**/*.{ts,tsx}'`. Le dossier de `frontend-professional` s'est vidé, celui de `frontend-individual` naît vide : garder les deux présents évite de faire diverger trois feuilles de style pour une raison passagère.                                                          |
| `app/site-url.ts` ajouté au périmètre                                      | Trois fichiers doivent s'accorder sur la même URL canonique — `metadataBase`, `robots.ts`, `sitemap.ts`. Trois copies divergeraient au premier changement de domaine, et la divergence serait silencieuse : un sitemap qui annonce un autre hôte que les balises canoniques n'échoue pas, il est ignoré.                          |
| Variable `SITE_URL` ajoutée hors de la liste du ticket                     | Le ticket demande des métadonnées Open Graph et un sitemap, qui exigent tous deux une URL absolue. Sans préfixe `NEXT_PUBLIC_` : ses consommateurs tournent au build ou sur le serveur, jamais dans le navigateur — même raisonnement que pour `API_INTERNAL_URL`.                                                                |
| Génération statique obtenue sans `force-static`                            | Le ticket demande de « l'activer lorsque c'est pertinent ». Rien à activer : sans API dynamique, Next prérend déjà tout au build. L'écrire quand même banaliserait la directive, alors que sa valeur tient à sa rareté.                                                                                                           |
| Ni image Open Graph ni manifest                                            | Périmètre arbitré à l'ouverture du ticket. Les deux réclament des visuels que le dépôt n'a pas, et une carte de partage annonçant une image absente vaut moins qu'une carte sobre. Détaillé dans « Le volet SEO de `frontend-individual` ».                                                                                       |
| Deuxième carte sur la page d'accueil                                       | Le ticket ne décrit pas la page. Celle du patron atteste le câblage du monorepo ; il manquait de quoi attester le volet propre à cette application-ci, d'où deux liens vers `/robots.txt` et `/sitemap.xml` qui se vérifient d'un coup d'œil.                                                                                     |
| Pas de `tailwind.config.ts`                                                | Le ticket demande de reprendre « le tailwind.config de FRONT-01 », qui n'existe pas : Tailwind v4 n'a plus de configuration JavaScript. Même arbitrage qu'en SHARED-02 et FRONT-01 — le thème **est** le CSS partagé.                                                                                                             |
| `@repo/api-client` absent des dépendances et de `transpilePackages`        | Le package relève de SHARED-03 et n'existe pas : une dépendance `workspace:*` vers un package inexistant fait échouer `pnpm install`. Même écart qu'en FRONT-01, et il se lèvera au même moment pour les trois applications.                                                                                                      |
| `@repo/typescript-config` et `@repo/tailwind-config`                       | Le ticket écrit `@repo/config-typescript` et `@repo/config-tailwind` : ce sont les noms des dossiers, pas ceux des packages. Même écart qu'en SHARED-02 et FRONT-01.                                                                                                                                                              |
| Textes d'interface accentués                                               | Le dépôt écrit son français sans accents hors des `.md`, mais la règle ne peut pas s'étendre à ce qui s'affiche — et moins encore ici : ces textes sont ceux que liront les propriétaires d'animaux, et les moteurs. Commentaires et messages de commit restent sans accents.                                                     |

> **Note.** Le critère « aucun composant n'est dupliqué depuis
> frontend-professional » a été tenu par la seule voie qui le rende vrai
> durablement : déplacer le composant partagé plutôt que le copier. C'est
> pourquoi ce ticket touche `frontend-professional` et `@repo/ui` en plus de son
> propre dossier — les deux applications ont été relancées et comparées après le
> déplacement, celle de FRONT-01 est inchangée à l'écran.

### Écarts assumés avec le ticket FRONT-03

| Écart                                                        | Raison                                                                                                                                                                                                                                                                     |
| ------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `proxy.ts` et `app/(auth)/login/`, du périmètre de FRONT-07  | « Redirection vers la page de connexion par défaut » ne s'implémente pas sans eux. Les chemins sont ceux que FRONT-07 annonce, pour qu'il remplace une fonction au lieu de re-router l'application ; rien n'y vérifie de jeton.                                            |
| `proxy.ts` et non `middleware.ts`                            | Next 16 a renommé la convention. L'ancien nom fonctionne encore mais fait avertir **chaque build**, exactement ce que FRONT-01 a refusé en désactivant `agentRules`. FRONT-07 écrit `middleware.ts` dans son périmètre : c'est le même fichier sous son ancien nom.        |
| `@tanstack/react-table` ajouté à `@repo/ui`                  | Conséquence directe du « sinon créer une extension dans le package partagé » du ticket, la vérification ayant conclu par la négative — `table.tsx` est purement présentationnel, et le registre shadcn n'a pas de `data-table` à livrer.                                   |
| `Pagination` du registre écarté au profit de boutons         | Envisagé, puis rejeté après lecture : ce composant est fait de **liens**, donc destiné à une pagination portée par l'URL. La page d'une `DataTable` est un état de la table, sans adresse propre — et un `<a>` sans `href` n'est ni focalisable ni actionnable au clavier. |
| `lucide-react` déclarée par l'application                    | `@repo/ui` la porte déjà, mais le `node_modules` strict de pnpm interdit d'importer ce qu'on ne déclare pas : les icônes de la navigation sont une donnée de l'application, pas du package. Même version que lui, pour que pnpm n'en installe qu'une.                      |
| `force-dynamic` sur `(protected)` seulement                  | Le ticket demande qu'il n'y ait pas de rendu statique public. Le contenu privé est dans ce groupe ; la page de connexion n'a rien à cacher, et l'y soumettre l'aurait ralentie sans rien protéger.                                                                         |
| `TooltipProvider` monté dans l'application                   | Les info-bulles de la barre repliée en dépendent, et ce fournisseur n'a de sens que là où des info-bulles existent. Le placer dans le `ThemeProvider` partagé l'aurait imposé aux deux autres applications sans raison.                                                    |
| Deux sections de démonstration (`cliniques`, `utilisateurs`) | Un fil d'Ariane qui n'affiche jamais qu'un seul niveau ne prouve rien, et le rôle lu par la garde resterait une intention sans écran pour l'afficher.                                                                                                                      |
| Données de la table écrites en dur                           | Ni API ni cache avant SHARED-03 et FRONT-04. Ce que ces lignes servent à montrer, c'est que l'extension du package trie, filtre et pagine — la même logique que les pages de démonstration de FRONT-01 et FRONT-02.                                                        |

### Hooks de pre-commit

`pnpm install` installe les hooks Git en même temps que les dépendances : le
script `prepare` lance [Husky](https://typicode.github.io/husky/), qui fait
pointer `core.hooksPath` sur `.husky/_`. Rien d'autre à faire, rien à relancer.

| Hook                | Ce qu'il lance      | Ce qu'il vérifie                     |
| ------------------- | ------------------- | ------------------------------------ |
| `.husky/pre-commit` | `lint-staged`       | Le contenu des fichiers **indexés**. |
| `.husky/commit-msg` | `commitlint --edit` | Le message du commit.                |

`lint-staged` ne traite **que les fichiers indexés**, jamais le dépôt entier —
c'est ce qui garde le hook sous les dix secondes :

| Fichiers indexés            | Traitement                                          |
| --------------------------- | --------------------------------------------------- |
| `*.{ts,tsx,js,jsx,mjs,cjs}` | `eslint --fix` puis `prettier --write`              |
| `*.{json,md,yaml,yml}`      | `prettier --write`                                  |
| `backend/**/*.py`           | `ruff check --fix` puis `ruff format`, via `uv run` |

Ce qui est corrigeable est **corrigé puis ré-indexé** : le commit part propre
sans rien vous demander. Ce qui ne l'est pas — erreur ESLint sans correction
automatique, règle Ruff non corrigeable, annotation de type manquante —
**interrompt le commit**. Le détail, chaque choix accompagné de sa raison, est
dans [`lint-staged.config.mjs`](lint-staged.config.mjs).

> **Le volet Python exige `uv` sur le poste.** Qui ne touche jamais au backend
> n'a rien à installer : cette entrée ne se déclenche que sur un `.py` indexé.

Trois situations, trois gestes :

| Situation                                        | Geste                                               |
| ------------------------------------------------ | --------------------------------------------------- |
| **Urgence** : livrer sans passer par les hooks   | `git commit --no-verify`                            |
| Environnement sans hooks (image Docker, CI)      | `HUSKY=0 pnpm install`                              |
| Les hooks ne se déclenchent plus                 | `pnpm prepare`                                      |
| Client Git graphique : `node: command not found` | Exporter le `PATH` depuis `~/.config/husky/init.sh` |

Le troisième cas se produit après un `HUSKY=0 pnpm install` : un `pnpm install`
ultérieur ne réinstalle rien s'il n'a rien à installer, et ne relance donc pas
`prepare`. `pnpm prepare` repose les hooks en une seconde.

**`--no-verify` est réservé aux urgences** — un correctif de production à 3 h du
matin, pas un lint qui agace. Ce qu'il laisse passer, la CI (QA-01 et QA-02) le
rattrapera de toute façon, avec un aller-retour de plus.

Le dernier cas vient de ce qu'un client graphique n'hérite pas du `PATH` d'un
terminal de connexion : il ne trouve donc pas Node, dont dépendent `lint-staged`
et `commitlint`. Husky lit `~/.config/husky/init.sh` avant chaque hook, c'est là
que ça se répare :

```sh
# ~/.config/husky/init.sh
export PATH="/opt/homebrew/bin:$PATH"
```

(Les binaires du dépôt, eux, sont déjà trouvés : husky place `node_modules/.bin`
en tête du `PATH` de ses hooks.)

### Convention de commit

Les messages suivent [Conventional Commits](https://www.conventionalcommits.org/fr/),
vérifiés par commitlint :

```
type(scope facultatif): sujet
```

Huit types, et un sujet en français à l'infinitif, sans majuscule initiale ni
point final :

| Type       | Quand l'employer                                      |
| ---------- | ----------------------------------------------------- |
| `feat`     | Nouvelle fonctionnalité.                              |
| `fix`      | Correction d'un défaut.                               |
| `chore`    | Outillage, dépendances, tâche sans effet fonctionnel. |
| `docs`     | Documentation seule.                                  |
| `refactor` | Réécriture à comportement constant.                   |
| `test`     | Ajout ou modification de tests.                       |
| `ci`       | Intégration continue.                                 |
| `build`    | Build, conteneurs, publication.                       |

Le scope est **facultatif** ; s'il est présent, il désigne un workspace : `api`,
`professional`, `individual`, `admin`, `ui`, `config-typescript`,
`config-tailwind`, `docker`, `documentation`. La liste
suit l'arborescence réelle — **un nouveau workspace ajoute son scope à
[`commitlint.config.mjs`](commitlint.config.mjs) dans la pull request qui le
crée**.

```
chore: configurer les workspaces pnpm (SETUP-02)
feat(api): exposer la sonde de santé
```

Les commits de merge, de revert, de fixup et de squash sont ignorés d'office :
un `git merge` local ne sera pas rejeté.

### Écarts assumés avec le ticket SETUP-04

| Écart                                         | Raison                                                                                                                                 |
| --------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| `.mjs` plutôt que `.js` pour les deux configs | Le `package.json` racine n'est pas `"type": "module"` : un `.js` serait du CommonJS, seul îlot du genre dans un dépôt entièrement ESM. |
| Glob étendu à `mjs` et `cjs`                  | Les fichiers de configuration du dépôt sont eux-mêmes en `.mjs`. Sans cet ajout, le hook ne couvrirait pas ses propres sources.        |
| `perf`, `revert` et `style` retirés des types | Le ticket fixe une liste de huit types. `style` n'a plus d'objet : Prettier et Ruff formatent seuls.                                   |
| `documentation` ajouté aux scopes             | Workspace déjà déclaré dans [`pnpm-workspace.yaml`](pnpm-workspace.yaml) ; la liste suit les workspaces réels.                         |
| Aucune vérification de types dans le hook     | Le ticket impose moins de dix secondes. `mypy` et `tsc` relèvent de la CI (QA-01, QA-02) ; le hook garde le lint et le formatage.      |

## Licence

[MIT](LICENSE).
