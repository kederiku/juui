#!/bin/sh
# Creation de la base des tests d'integration (INFRA-01, consommee par BACK-12).
#
# QUAND CE SCRIPT TOURNE
# L'image PostgreSQL joue le contenu de /docker-entrypoint-initdb.d UNE SEULE
# FOIS, a la creation du cluster -- c'est-a-dire au tout premier demarrage du
# volume `postgres_data`, et jamais ensuite. Modifier ce fichier n'aura donc
# d'effet qu'apres un :
#
#   docker compose --project-directory . -f docker/docker-compose.yml down -v
#
# qui detruit les donnees au passage. Les fichiers sont joues dans l'ordre
# alphabetique, d'ou le prefixe numerique : INFRA-02 et suivants inserent le
# leur sans avoir a renommer celui-ci.
#
# POURQUOI UN .sh ET PAS UN .sql
# Le ticket parle de « scripts SQL » et .env.example promet que le nom de la
# base de test reste modifiable sans toucher a ce fichier. Les deux sont
# inconciliables : un .sql pose la n'interpole aucune variable d'environnement.
# Le shell, lui, lit POSTGRES_TEST_DB -- que docker-compose.yml lui transmet.
#
# DEUX PRECAUTIONS D'ECRITURE
# `set -u` est volontairement absent, et aucun `exit` n'apparait : si le bit
# executable venait a se perdre, l'entrypoint SOURCERAIT ce script dans son
# propre shell, ou l'un comme l'autre saboterait la suite de l'initialisation.
set -e

if [ -z "${POSTGRES_TEST_DB:-}" ]; then
  echo "INFRA-01 : POSTGRES_TEST_DB n'est pas defini, aucune base de test creee." >&2
elif [ "$POSTGRES_TEST_DB" = "$POSTGRES_DB" ]; then
  echo "INFRA-01 : POSTGRES_TEST_DB vaut POSTGRES_DB, aucune base de test creee." >&2
else
  echo "INFRA-01 : creation de la base de test $POSTGRES_TEST_DB..."
  # CREATE DATABASE n'accepte ni parametre lie ni IF NOT EXISTS. `\gexec`
  # execute le texte produit par la requete precedente : c'est la facon
  # canonique de contourner les deux, et `format(%I)` cite l'identifiant
  # correctement au passage.
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<EOSQL
SELECT format('CREATE DATABASE %I OWNER %I', '${POSTGRES_TEST_DB}', '${POSTGRES_USER}')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${POSTGRES_TEST_DB}')\gexec
EOSQL
fi
