---
title: Démarrer la pile
description: Les deux parcours de démarrage — services en conteneurs et API sur le poste, ou toute la pile avec make up.
---

# Démarrer la pile

Deux parcours mènent à une pile qui tourne — les services d'infrastructure en conteneurs et l'API
sur le poste, ou bien tout le dépôt, worker et frontends compris, d'un seul `make up`. Les deux
partagent la même [allocation des ports](../infrastructure/ports-et-services.md).

## Démarrer aujourd'hui

Deux morceaux démarrent : les services d'infrastructure, en conteneurs, et
l'API, sur le poste.

D'abord l'infrastructure — PostgreSQL avec sa base de test `app_test` et la
console pgAdmin, Redis, MinIO avec son bucket applicatif, et Mailpit qui capte
le courrier sortant :

```bash
docker compose --project-directory . -f docker/docker-compose.yml up -d
```

Le `--project-directory .` n'est pas décoratif, et il n'est pas non plus
facultatif : le fichier compose vit dans `docker/` alors que le `.env` est à la
racine, et c'est ce drapeau qui accorde les deux. Il commande aussi la
résolution des chemins montés — le détail est dans
`docker/docker-compose.yml`, en tête de fichier.

pgAdmin répond sur [http://localhost:5050](http://localhost:5050) ; s'y connecter avec
`PGADMIN_DEFAULT_EMAIL` et `PGADMIN_DEFAULT_PASSWORD`. Le serveur
« Juui - PostgreSQL local » y est déjà enregistré, mot de passe compris : il n'y
a **rien à saisir** pour ouvrir la base. La console de MinIO, elle, répond sur
[http://localhost:9001](http://localhost:9001) — voir la page
[MinIO](../infrastructure/minio.md). La boîte
de réception de Mailpit s'ouvre sur [http://localhost:8025](http://localhost:8025), sans identifiants :
tout e-mail émis par la pile y atterrit, et aucun n'en sort — voir la page
[Mailpit](../infrastructure/mailpit.md).

Puis l'API, sur le poste — c'est le principe de ce parcours, le parcours
conteneurisé la fait tourner sur l'image d'INFRA-04 :

```bash
cd backend/api && uv run uvicorn app.main:app --reload
```

La documentation interactive répond sur [http://localhost:8000/docs](http://localhost:8000/docs). L'API ne
sert encore aucune route — voir la [section Backend](../backend/index.md).

Depuis BACK-03, elle **valide sa configuration au démarrage** et refuse de partir
si une variable obligatoire manque — d'où la copie de `backend/api/.env` faite à
l'installation. Le message d'erreur nomme alors chaque variable en défaut.

Depuis BACK-05, elle **ouvre son pool PostgreSQL au démarrage** et l'éprouve par
un `SELECT 1`. Le service `postgres` doit donc tourner, sans quoi le processus
s'arrête en nommant l'hôte injoignable, avec un code de sortie 3 — plutôt que de
paraître sain et d'échouer au premier appel.

Enfin les interfaces et le site de documentation — les workspaces pnpm qui
définissent un script `dev` :

```bash
pnpm dev
```

La commande démarre en parallèle les serveurs de développement de tout le
dépôt : l'interface professionnelle répond sur [http://localhost:3001](http://localhost:3001), celle
des particuliers sur [http://localhost:3002](http://localhost:3002) et le back-office sur
[http://localhost:3003](http://localhost:3003) — ce dernier redirigeant aussitôt vers sa page de
connexion, voir [Le back-office de `frontend-admin`](https://github.com/kederiku/juui#le-back-office-de-frontend-admin).
Le site de documentation démarre lui aussi, sur [http://localhost:3004](http://localhost:3004).

Pour n'en démarrer qu'une, la filtrer par le nom de son workspace :

```bash
pnpm --filter frontend-individual run dev
```

## La pile complète, avec Docker

:::note Pile complète depuis INFRA-05b
La pile est **complète** depuis INFRA-05b.
`docker/docker-compose.yml` porte les douze
services du dépôt : `postgres`, `pgadmin`, `redis`, `redisinsight`, `minio`,
`minio-init`, `mailpit`, `api`, `worker` et les trois frontends. Onze démarrent
avec un `up` nu — `redisinsight` attend son profil `tools`.

Le `worker` consomme les tâches de fond depuis BACK-15 — voir
[Le worker](../infrastructure/index.md#le-worker).
:::

L'installation tient en trois commandes :

```bash
git clone git@github.com:kederiku/juui.git && cd juui
cp .env.example .env
make up
```

| Cible                   | Effet                                                                     |
| ----------------------- | ------------------------------------------------------------------------- |
| `make help`             | Cible par défaut : liste toutes les cibles.                               |
| `make up`               | Démarre toute la pile en arrière-plan, sur les images servies.            |
| `make dev`              | Démarre la pile en mode développement — code monté, rechargement à chaud. |
| `make down`             | Arrête la pile et libère les ports ; les volumes survivent.               |
| `make restart`          | Redémarre les conteneurs sans les recréer.                                |
| `make logs service=api` | Suit les logs d'un service.                                               |
| `make shell-api`        | Ouvre un shell `bash` dans le conteneur d'API.                            |
| `make mail`             | Ouvre la boîte de réception Mailpit dans le navigateur.                   |

Les cibles de base de données et de qualité sont décrites dans
[Cibles `make` de la racine](../infrastructure/makefile-et-scripts.md#cibles-make-de-la-racine).
`make help` fait foi, comme dans `backend/api/Makefile`, qui adopte les mêmes
conventions et auquel le `Makefile` de la racine délègue.

Le fichier compose vit dans `docker/`, le `.env` à la racine. Sans
`--project-directory`, `docker compose` chercherait son `.env` dans `docker/` et
n'en trouverait pas : c'est cette commande que `make up` encapsule.

```bash
docker compose --project-directory . -f docker/docker-compose.yml up -d
```

Elle démarre la pile sur les images **servies** : l'API sans rechargement, les
frontends sur leur sortie `standalone`. Pour travailler sur le code, c'est la
variante à deux fichiers qu'il faut — voir
[Le mode développement](../infrastructure/mode-developpement.md).

Ajouter `--profile tools` pour démarrer en plus les consoles d'inspection
optionnelles — aujourd'hui RedisInsight, qui s'ouvre déjà raccordée aux deux
bases Redis.

:::warning Mot de passe modifié dans `.env`
PostgreSQL ne lit ses
identifiants qu'à la **première** création de son volume : les changer ensuite
reste sans effet tant que le volume vit. `make db-reset` fait cela proprement :
il ne détruit que le volume de PostgreSQL — les fichiers de MinIO, le cache
Redis et la configuration de pgAdmin survivent —, demande confirmation
(`force=1` pour la sauter), puis rejoue les migrations. MinIO, lui, relit ses
identifiants à chaque recréation — un `make up` suffit, sans rien perdre.
:::

Node et `uv` restent utiles sur le poste même avec ce parcours : les hooks de
pre-commit s'exécutent en dehors des conteneurs.

Les écarts assumés avec le ticket SETUP-05 sont consignés au
[registre des écarts](../ecarts/setup.md#écarts-assumés-avec-le-ticket-setup-05).
