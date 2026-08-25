---
title: "L'image du service d'API"
description: "L'image Docker de l'API : ses étages, ce que fait l'entrypoint, l'IP réelle du client et la taille obtenue."
---

# L'image du service d'API

Cette page décortique l'image Docker du service d'API — ses trois cibles de build, l'entrypoint
exécuté avant la commande du conteneur, la question de l'IP réelle du client et la façon correcte
de lire la taille obtenue.

Le service `api` est le premier de la pile à se **construire depuis le dépôt** :
les cinq autres tirent une image publique. Son Dockerfile vit dans
`docker/api/` et expose trois cibles utiles :

| Cible    | Ce qu'elle fait                                                                         | Qui l'utilise                  |
| -------- | --------------------------------------------------------------------------------------- | ------------------------------ |
| `prod`   | uvicorn sans rechargement, `WEB_CONCURRENCY` processus, dépendances applicatives seules | le service `api` du compose    |
| `dev`    | `uvicorn --reload`, groupe `dev` installé (Ruff, Mypy, Pytest), installation éditable   | `docker-compose.override.yml`  |
| `worker` | même image que `prod`, commande `taskiq worker`                                         | le service `worker` du compose |

`docker compose up` construit la cible `prod`. Pour construire une cible à la
main, hors compose :

```bash
docker build --target dev --build-context scripts=docker/api -t juui-api:dev -f docker/api/Dockerfile backend/api
```

Le `--build-context` n'est pas décoratif. Le contexte de build est
`backend/api` — c'est ce qui rend
`backend/api/.dockerignore` effectif et ce qui évite
d'envoyer `node_modules` au démon — mais `entrypoint.sh` vit dans `docker/api/`,
donc **hors** de ce contexte. Ce drapeau l'y raccroche ; le fichier compose fait
la même chose avec sa clé `additional_contexts`. Sans lui, le build échoue sur un
`COPY --from=scripts` qui ne trouve rien.

## Ce que fait l'entrypoint

`docker/api/entrypoint.sh` s'exécute avant la
commande du conteneur, dans les trois cibles :

1. **il attend PostgreSQL** — une vraie connexion `asyncpg`, pas un test de port
   ouvert : pendant son initialisation, le serveur écoute déjà sans accepter
   personne ;
2. **il applique les migrations**, `alembic upgrade head` — l'étape, écrite
   d'avance par INFRA-04, s'est activée d'elle-même quand BACK-07 a livré
   `alembic.ini` ; l'`env.py` sérialise les migrateurs concurrents (`api` et
   `worker --scale`) par un verrou consultatif PostgreSQL ;
3. **il `exec` la commande**, qui hérite du PID 1 et reçoit donc le `SIGTERM` de
   `docker stop`.

Ces trois étapes se lisent dans le journal du service :

```bash
docker compose --project-directory . -f docker/docker-compose.yml logs api
```

```
INFRA-04 : PostgreSQL joignable sur postgres:5432 (tentative 1).
INFRA-04 : application des migrations (alembic upgrade head)...
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFRA-04 : demarrage de -- uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers
```

L'API répond alors sur [http://localhost:8000/docs](http://localhost:8000/docs). La sonde du service vise
`/health/live` (BACK-08) : la sonde de **vie**, sans dépendance externe — c'est
exactement ce qu'un healthcheck de conteneur doit tester, un PostgreSQL tombé ne
se répare pas en redémarrant l'API. L'état des dépendances, lui, se lit sur
`/health/ready`, qui nomme le composant défaillant.

## L'IP réelle du client

Un conteneur ne voit **jamais** l'IP réelle de celui qui l'appelle : les requêtes
publiées par Docker lui arrivent avec celle de la passerelle — `192.168.65.1`
sous Docker Desktop. Se donner l'occasion de le constater :

```bash
curl -s -o /dev/null http://localhost:8000/health/live
docker compose --project-directory . -f docker/docker-compose.yml logs api | tail -1
```

`--proxy-headers` seul n'y change rien : uvicorn ne substitue l'adresse annoncée
par l'en-tête `X-Forwarded-For` que si le pair qui l'envoie figure dans
`FORWARDED_ALLOW_IPS`. Rien ne pose cet en-tête dans la pile de développement, et
la valeur par défaut ne fait confiance qu'à `127.0.0.1` : la passerelle continue
donc de s'afficher, et c'est le comportement attendu. Le mécanisme se vérifie en
élargissant temporairement la confiance :

```bash
FORWARDED_ALLOW_IPS='*' docker compose --project-directory . -f docker/docker-compose.yml up -d api
curl -s -o /dev/null -H 'X-Forwarded-For: 203.0.113.7' http://localhost:8000/health/live
docker compose --project-directory . -f docker/docker-compose.yml logs api | tail -1
# INFO:     203.0.113.7:0 - "GET /health/live HTTP/1.1" 200 OK
```

Remettre ensuite la valeur du `.env` — `*` ferait confiance à n'importe quel
client, qui n'aurait plus qu'à s'annoncer sous l'IP de son choix. C'est en
production, derrière un proxy qui pose réellement l'en-tête, que la variable
compte : sans l'adresse de ce proxy, toutes les requêtes semblent venir de lui et
la limitation de renvoi d'OTP par IP (BACK-17) devient **globale**.

## Taille de l'image

Le critère d'acceptation demande moins de 400 Mo. Trois chiffres différents
circulent, et il vaut mieux savoir lequel on lit :

```bash
docker image ls --tree juui-api
```

| Mesure                           | Valeur       | Ce que c'est                                                                     |
| -------------------------------- | ------------ | -------------------------------------------------------------------------------- |
| `CONTENT SIZE`                   | **≈ 91 Mo**  | ce qui transite vers un registre, couches compressées                            |
| somme des couches décompressées  | **≈ 310 Mo** | l'« image size » d'avant Docker 25, et la mesure usuelle                         |
| `DISK USAGE` (`docker image ls`) | ≈ 402 Mo     | sous le magasin containerd : les blobs compressés **et** leur copie décompressée |

Le service tient donc largement sous la barre ; c'est `DISK USAGE` qui compte
deux fois la même chose. La taille réellement occupée dans le conteneur se
mesure sans ambiguïté :

```bash
docker run --rm --entrypoint sh juui-api:prod -c 'du -sm /'   # -> 293
```

Le virtualenv en représente 144 Mo, dont 30 pour `botocore` et 32 pour les `.pyc`
précompilés à l'installation (`UV_COMPILE_BYTECODE=1`, qui échange ces 32 Mo
contre un démarrage plus rapide).

Les écarts assumés avec le ticket INFRA-04 sont consignés au
[registre des écarts](../ecarts/infra.md#écarts-assumés-avec-le-ticket-infra-04).
