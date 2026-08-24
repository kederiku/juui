#!/bin/sh
# Point d'entree des conteneurs batis sur l'image d'API (INFRA-04).
#
# CE QU'IL FAIT, DANS CET ORDRE
#   1. attendre que PostgreSQL accepte reellement une connexion ;
#   2. appliquer les migrations, quand il y en a ;
#   3. `exec` la commande du conteneur -- uvicorn pour `prod` et `dev`,
#      `taskiq worker` pour `worker` (INFRA-05b).
#
# QUI L'EXECUTE
# Les trois cibles de docker/api/Dockerfile le declarent en ENTRYPOINT, worker
# compris. Ce qui les distingue est leur CMD, que la derniere ligne d'ici
# remplace au processus courant.
#
# VARIABLES LUES
# POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER, POSTGRES_PASSWORD et POSTGRES_DB,
# toutes documentees dans le .env.example de la racine et toutes deja lues par
# BACK-03 sous ces memes noms. Ce script n'en introduit AUCUNE autre : un
# reglage qui n'existerait que dans un entrypoint serait invisible du recensement
# que SETUP-05 s'est attache a tenir.
#
# `set -e` : la premiere commande en echec interrompt le demarrage, et le
# conteneur s'arrete avec un code non nul plutot que de servir sur une base
# absente.
set -e

# ---------------------------------------------------------------------------
# 1. Attendre PostgreSQL
# ---------------------------------------------------------------------------
# POURQUOI PAS `pg_isready` : il faudrait installer postgresql-client dans une
# image que le ticket veut minimale, pour une commande utilisee une seule fois
# au demarrage.
#
# POURQUOI PAS UN SIMPLE TEST TCP : un port ouvert n'est pas une base qui
# accepte l'authentification. C'est exactement la lecon inscrite dans le
# healthcheck du service postgres (INFRA-01) : pendant son initialisation, le
# serveur temporaire ecoute deja sans accepter personne. On ouvre donc une VRAIE
# connexion, avec asyncpg -- deja present dans le virtualenv, il n'y a rien a
# ajouter a l'image.
#
# Le `depends_on: service_healthy` du fichier compose couvre deja le demarrage
# de la pile entiere. Cette boucle couvre le reste : un `docker compose up api`
# seul, un `docker run` a la main, ou un PostgreSQL redemarre pendant que ce
# conteneur tourne.
python - <<'PY'
"""Attend que PostgreSQL accepte une connexion, ou echoue au bout de 30 essais."""

import asyncio
import os
import sys

import asyncpg

HOST = os.environ.get("POSTGRES_HOST", "postgres")
PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
ATTEMPTS = 30

# Erreurs qui signifient « pas encore pret », et elles seules. OSError couvre le
# refus de connexion et le nom d'hote pas encore resolvable ; TimeoutError en
# est une sous-classe depuis Python 3.11. Tout le reste -- mot de passe refuse,
# base inexistante -- est une erreur de CONFIGURATION : la reessayer trente fois
# ne ferait que retarder de trente secondes un message qu'il faut lire tout de
# suite.
RETRYABLE = (OSError, asyncpg.PostgresConnectionError, asyncpg.CannotConnectNowError)


async def wait_for_postgres() -> int:
    """Boucle jusqu'a une connexion reussie. Retourne le code de sortie du script."""
    last_error: Exception | None = None

    for attempt in range(1, ATTEMPTS + 1):
        try:
            connection = await asyncpg.connect(
                host=HOST,
                port=PORT,
                user=os.environ.get("POSTGRES_USER"),
                password=os.environ.get("POSTGRES_PASSWORD"),
                database=os.environ.get("POSTGRES_DB"),
                timeout=5,
            )
        except RETRYABLE as error:
            last_error = error
            await asyncio.sleep(1)
            continue

        await connection.close()
        print(f"INFRA-04 : PostgreSQL joignable sur {HOST}:{PORT} (tentative {attempt}).")
        return 0

    print(
        f"INFRA-04 : {HOST}:{PORT} injoignable apres {ATTEMPTS} tentatives -- {last_error}",
        file=sys.stderr,
    )
    return 1


sys.exit(asyncio.run(wait_for_postgres()))
PY

# ---------------------------------------------------------------------------
# 2. Migrations
# ---------------------------------------------------------------------------
# alembic.ini N'EXISTE PAS ENCORE : il arrive avec BACK-07, en meme temps que
# les premieres migrations. INFRA-04 l'attribuait a BACK-05, qui n'a livre que le
# socle SQLAlchemy -- moteur, session et mixins, sans outil de migration. La garde de presence est ce qui permet d'ecrire
# l'etape des maintenant sans casser le demarrage d'aujourd'hui -- et l'etape
# s'activera d'elle-meme, sans qu'on ait a revenir sur ce fichier.
#
# Le repertoire de travail est /app, ou le Dockerfile a copie le contenu de
# backend/api : c'est la que se trouvera alembic.ini.
#
# A ARBITRER EN BACK-07 : le service `worker` d'INFRA-05b partage cet entrypoint
# et reste `--scale`-able. Plusieurs `alembic upgrade head` simultanes sur la
# meme base sont une course. Sans objet tant qu'aucune migration n'existe ; la
# reponse habituelle est un verrou consultatif PostgreSQL pris par env.py.
if [ -f alembic.ini ]; then
  echo "INFRA-04 : application des migrations (alembic upgrade head)..."
  alembic upgrade head
else
  echo "INFRA-04 : alembic.ini absent, migrations non configurees (BACK-07) -- etape sautee."
fi

# ---------------------------------------------------------------------------
# 3. Ceder la place a la commande du conteneur
# ---------------------------------------------------------------------------
# `exec` REMPLACE ce shell par la commande, qui herite donc du PID 1. Sans lui,
# le shell resterait PID 1 et garderait pour lui le SIGTERM de `docker stop` :
# uvicorn ne fermerait jamais proprement ses connexions, et Docker le tuerait au
# bout des dix secondes de grace.
echo "INFRA-04 : demarrage de -- $*"
exec "$@"
