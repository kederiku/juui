#!/bin/sh
# Destruction et recreation du volume de donnees de PostgreSQL (INFRA-06).
#
# CE QU'IL FAIT, DANS CET ORDRE
#   1. demander confirmation -- l'operation detruit des donnees sans retour ;
#   2. identifier le volume monte par le service `postgres`, en le DEMANDANT
#      a Docker plutot qu'en reconstruisant son nom ;
#   3. supprimer le conteneur, puis le volume ;
#   4. recreer le service et attendre que sa sonde de sante passe au vert.
#
# CE QU'IL NE FAIT PAS : ni migrations ni seed. Ce sont deux cibles qui
# existent deja, et `make db-reset` les enchaine apres lui -- la sequence se
# lit dans le Makefile plutot qu'ici.
#
# CE QU'IL NE DETRUIT PAS : les volumes de MinIO, Redis, RedisInsight et
# pgAdmin. `docker compose down -v` les emporterait tous, c'est-a-dire les
# fichiers deposes dans le bucket. La cible s'appelle db-reset : elle s'arrete
# a la base.
#
# CE QUE LA RECREATION REJOUE : les scripts de /docker-entrypoint-initdb.d,
# donc la base de test app_test (INFRA-01) -- et la prise en compte d'un
# POSTGRES_PASSWORD modifie, que seul un volume neuf permet.
#
# APPELE PAR `make db-reset`, qui lui passe COMPOSE : l'invocation compose est
# ecrite une seule fois dans le depot, en tete du Makefile, et la recopier ici
# en ferait une seconde source de verite.
set -e

if [ -z "${COMPOSE:-}" ]; then
  echo "INFRA-06 : COMPOSE n'est pas defini -- ce script s'appelle par 'make db-reset'." >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# 1. Confirmation
# ---------------------------------------------------------------------------
# Aucun autre geste du depot ne detruit de donnees sans le dire. `force=1` la
# saute ; une entree non interactive echoue plutot que de detruire en silence.
if [ "${force:-}" != "1" ]; then
  if [ ! -t 0 ]; then
    echo "INFRA-06 : entree non interactive -- relancer avec 'make db-reset force=1'." >&2
    exit 1
  fi

  printf 'INFRA-06 : detruire la base de developpement et toutes ses donnees ? [o/N] '
  read -r reply
  case "$reply" in
    [oO] | [oO][uU][iI]) ;;
    *)
      echo 'INFRA-06 : abandon, rien n a ete touche.'
      exit 0
      ;;
  esac
fi

# ---------------------------------------------------------------------------
# 2. Identifier le volume
# ---------------------------------------------------------------------------
# On le DEMANDE a Docker au lieu de recomposer ${COMPOSE_PROJECT_NAME}_postgres_data :
# le prefixe vient du .env, et le reconstruire ici en ferait une valeur fausse
# le jour ou la pile tourne sous un autre nom de projet.
#
# `up -d postgres` d'abord : sans conteneur, rien a inspecter. La commande ne
# fait rien de plus si le service tourne deja.
#
# `$COMPOSE` n'est volontairement PAS entre guillemets : c'est une commande et
# ses arguments, a decouper en mots.
echo 'INFRA-06 : identification du volume de donnees de postgres...'
$COMPOSE up -d postgres

container=$($COMPOSE ps -q postgres)

# `eq .Type "volume"` : postgres monte AUSSI un bind sur
# /docker-entrypoint-initdb.d, qu'il ne faut pas confondre avec le volume.
volume=$(docker inspect \
  --format '{{ range .Mounts }}{{ if eq .Type "volume" }}{{ .Name }}{{ end }}{{ end }}' \
  "$container")

if [ -z "$volume" ]; then
  echo "INFRA-06 : postgres ne monte aucun volume nomme -- verifier docker/docker-compose.yml." >&2
  exit 1
fi

# GARDE-FOU : on ne supprime que ce que Compose a etiquete comme etant LE
# volume postgres_data d'un projet. Un montage introduit a la main ne passera
# pas.
label=$(docker volume inspect --format '{{ index .Labels "com.docker.compose.volume" }}' "$volume")
if [ "$label" != "postgres_data" ]; then
  echo "INFRA-06 : $volume n'est pas etiquete postgres_data (mais '$label') -- rien supprime." >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# 3. Detruire
# ---------------------------------------------------------------------------
# Le conteneur d'abord : Docker refuse de supprimer un volume encore monte. Le
# `--volumes` de `compose rm` ne concerne QUE les volumes anonymes -- le
# volume nomme se supprime a la main, juste apres.
echo "INFRA-06 : suppression du conteneur postgres et du volume $volume..."
$COMPOSE rm --stop --force --volumes postgres
docker volume rm "$volume" >/dev/null

# ---------------------------------------------------------------------------
# 4. Recreer
# ---------------------------------------------------------------------------
# `--wait` rend la main quand le healthcheck passe au vert, et pas avant : les
# migrations qui suivent partiraient sinon sur un serveur qui n'accepte encore
# personne (le postgres de l'image demarre deux fois pendant l'initialisation).
echo 'INFRA-06 : recreation du cluster, scripts d initialisation rejoues...'
$COMPOSE up -d --wait postgres

echo "INFRA-06 : base recreee sur un volume neuf -- $volume"
