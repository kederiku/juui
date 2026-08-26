#!/bin/sh
# Activation des extensions PostgreSQL du service (INFRA-09).
#
# QUAND CE SCRIPT TOURNE
# Comme son voisin 01 : une seule fois, a la creation du cluster -- au premier
# demarrage du volume `postgres_data`, jamais ensuite. Un volume anterieur a
# INFRA-09 ne le jouera donc jamais : c'est `make db-reset` qui l'y amene.
#
# POURQUOI LE PREFIXE 02, ET POURQUOI IL NE DOIT PAS CHANGER
# Les fichiers de /docker-entrypoint-initdb.d sont joues dans l'ordre
# alphabetique : le 01 a deja cree $POSTGRES_TEST_DB quand celui-ci demarre,
# et c'est cet ordre qui permet la double pose ci-dessous. Renomme en 00-, ce
# script viserait une base qui n'existe pas encore.
#
# POURQUOI CHAQUE BASE RECOIT SA POSE
# Une extension s'installe PAR BASE, pas par instance : la poser dans
# $POSTGRES_DB ne donne rien a $POSTGRES_TEST_DB, or la suite pytest (BACK-12)
# travaille sur la base de test. D'ou la fonction, appelee deux fois.
#
# ET LES BASES QUI EXISTENT DEJA ?
# Ce script n'atteint ni un volume de developpement anterieur ni une base
# geree en production. La regle du depot : le PREMIER ticket qui consomme une
# extension ouvre sa migration Alembic par un CREATE EXTENSION IF NOT EXISTS
# idempotent (BACK-20 pour pg_trgm, BACK-25 pour unaccent) -- les deux sont
# `trusted` depuis PostgreSQL 13, aucun superutilisateur requis.
#
# MEMES PRECAUTIONS D'ECRITURE QUE LE 01
# `set -u` volontairement absent, aucun `exit` : si le bit executable venait a
# se perdre, l'entrypoint SOURCERAIT ce script dans son propre shell, ou l'un
# comme l'autre saboterait la suite de l'initialisation.
set -e

# Pose les extensions du ticket dans la base passee en argument. Le heredoc
# est quote : rien a interpoler dans ce SQL, autant que le shell n'y touche
# pas.
enable_extensions() {
  echo "INFRA-09 : activation de pg_trgm et unaccent dans $1..."
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$1" <<'EOSQL'
-- pg_trgm : similarite par trigrammes, pour la recherche approximative au
-- rapprochement de fiches animal (BACK-20).
CREATE EXTENSION IF NOT EXISTS pg_trgm;
-- unaccent : recherche insensible aux accents sur les noms de personnes, de
-- cliniques et d'animaux (BACK-25).
CREATE EXTENSION IF NOT EXISTS unaccent;
-- Rien d'autre : une extension inutilisee est une surface de plus a
-- maintenir (INFRA-09).
EOSQL
}

enable_extensions "$POSTGRES_DB"

# Memes gardes que le 01 : la base de test peut ne pas exister.
if [ -z "${POSTGRES_TEST_DB:-}" ]; then
  echo "INFRA-09 : POSTGRES_TEST_DB n'est pas defini, extensions posees sur $POSTGRES_DB seulement." >&2
elif [ "$POSTGRES_TEST_DB" = "$POSTGRES_DB" ]; then
  echo "INFRA-09 : POSTGRES_TEST_DB vaut POSTGRES_DB, extensions deja posees." >&2
else
  enable_extensions "$POSTGRES_TEST_DB"
fi
