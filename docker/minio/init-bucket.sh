#!/bin/sh
# Amorcage du stockage objet : creation du bucket applicatif (INFRA-03,
# consomme par BACK-13).
#
# QUAND CE SCRIPT TOURNE
# A chaque `docker compose up`, dans le conteneur EPHEMERE `minio-init`, une
# fois `minio` declare sain. C'est l'inverse du script d'initialisation de
# PostgreSQL, qui n'est joue qu'a la creation du cluster : celui-ci est rejoue a
# chaque demarrage. D'ou l'exigence d'IDEMPOTENCE du ticket, qui tient dans les
# deux commandes de la fin.
#
# Le conteneur se termine ensuite, et `docker compose ps` le montre en
# `Exited (0)`. C'est le fonctionnement attendu, pas une panne.
#
# POURQUOI UN FICHIER VERSIONNE PLUTOT QU'UN `entrypoint` EN LIGNE
# Meme raisonnement que pour docker/redis/redis.conf : l'essentiel de ce que
# font ces quelques commandes tient dans leurs raisons, et un script peut les
# porter.
#
# DEUX PIEGES QUE CE SCRIPT EVITE
# 1. L'alias s'appelle `juui` et NON `local`. `local` existe deja dans la
#    configuration par defaut de mc, et pointe sur localhost:9000 avec le couple
#    `minioadmin/minioadmin` : le reutiliser donne un « Access Denied » a la
#    creation du bucket des que les identifiants racine ne sont pas ceux par
#    defaut -- ce qui est notre cas. Verifie, et proprement deroutant.
# 2. Les identifiants passent en ARGUMENTS de `mc alias set`, et non par la
#    variable d'environnement MC_HOST_<alias>, qui aurait l'air plus courte.
#    Celle-ci est une URL : un mot de passe contenant `@`, `/` ou `:` devrait y
#    etre percent-encode, et personne n'y penserait le jour ou
#    MINIO_ROOT_PASSWORD change.
set -e

# `${VAR:-}` plutot que `$VAR` : l'ecriture reste juste si `set -u` est ajoute
# un jour en tete de ce fichier.
if [ -z "${S3_BUCKET:-}" ]; then
  echo "INFRA-03 : S3_BUCKET n'est pas defini, aucun bucket cree." >&2
  exit 1
fi

# Repli sur le nom du service compose : .env.example documente S3_ENDPOINT_URL
# comme devant rester VIDE en production, ou boto3 parle directement a Amazon.
ENDPOINT="${S3_ENDPOINT_URL:-http://minio:9000}"

# Le `depends_on: service_healthy` du fichier compose garantit deja un MinIO
# pret quand la pile demarre en entier. Cette boucle couvre les autres cas --
# `docker compose up minio-init` seul, ou un serveur redemarre pendant que ce
# conteneur tourne -- et transforme un echec instantane en une attente bornee.
echo "INFRA-03 : connexion a $ENDPOINT..."
tentative=0
until mc alias set juui "$ENDPOINT" "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1; do
  tentative=$((tentative + 1))
  if [ "$tentative" -ge 30 ]; then
    echo "INFRA-03 : $ENDPOINT injoignable apres 30 tentatives, abandon." >&2
    exit 1
  fi
  sleep 1
done

# `--ignore-existing` est ce qui rend ce script rejouable : sans lui, le
# deuxieme `docker compose up` echouerait sur un « bucket already exists ».
echo "INFRA-03 : creation du bucket $S3_BUCKET s'il n'existe pas..."
mc mb --ignore-existing "juui/$S3_BUCKET"

# La policy VOULUE est l'absence d'acces anonyme. BACK-13 sert les fichiers par
# des URLs PRE-SIGNEES, qui portent leur propre autorisation et expirent ; un
# bucket ouvert en `download` rendrait lisible de tous n'importe quelle clef
# devinee -- photos et documents de sante compris.
#
# C'est deja le defaut d'un bucket neuf. L'ecrire couvre le cas ou quelqu'un
# aurait ouvert le bucket depuis la console : le demarrage suivant le referme.
mc anonymous set none "juui/$S3_BUCKET"

echo "INFRA-03 : stockage objet pret -- $ENDPOINT/$S3_BUCKET"
