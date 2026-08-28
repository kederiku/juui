#!/bin/sh
# Preuve que le client genere appelle reellement l'API (SHARED-03).
#
# POURQUOI UN FICHIER PLUTOT QU'UNE RECETTE EN LIGNE
# Trois etapes qui doivent s'enchainer dans UN meme shell -- compiler, executer,
# nettoyer -- et make 3.81 n'a pas de .ONESHELL : chaque ligne de recette y est
# un shell distinct. Le nettoyage doit par ailleurs avoir lieu meme quand la
# verification echoue, ce qu'un `trap` fait et qu'une suite de lignes ne fait
# pas.
#
# CE QUE CETTE VERIFICATION VAUT
# Elle appelle les FONCTIONS DE REQUETE du client genere -- celles-la memes que
# les hooks appellent -- contre le backend reel, et verifie la forme des donnees
# rendues. Depuis FRONT-04, elle joue aussi la couche de cache posee au-dessus :
# politique de reessai, appariement par prefixe d'un vrai QueryCache, routage
# global des 401. Elle ne rend toujours pas les hooks React : cela demande un
# runner de test frontend, qui appartient a QA-02. L'ecart est consigne au
# registre.
#
# CE QUI NE PASSE PAS PAR ICI
# L'algebre des clefs de cache et la traduction des erreurs se prouvent HORS
# LIGNE, sans backend et sans compilation : `pnpm --filter @repo/api-client test`
# (scripts/verify-query-keys.ts et scripts/verify-errors.ts). Une preuve qui
# exigerait la pile pour comparer deux tableaux ne tournerait jamais en
# integration continue.
#
# POURQUOI UNE COMPILATION JETABLE
# Node 24 efface les types a la volee, mais reste un resolveur ESM : il exige
# des extensions explicites, or Orval ecrit ses imports relatifs sans extension.
# Une passe `tsc` vers CommonJS, dans un dossier ignore par git, contourne cela
# sans ajouter la moindre dependance -- TypeScript est deja la. Le raisonnement
# complet est en tete de packages/api-client/tsconfig.verify.json.
#
# PREREQUIS : la pile demarree (`make dev`). C'est le VRAI service qui est
# interroge, pas un double -- c'est justement la derive entre le schema et le
# service que SHARED-03 existe pour rendre impossible.
set -e

PACKAGE="packages/api-client"
BUILD_DIR="$PACKAGE/.verify"

# L'adresse que lira le mutator. `API_INTERNAL_URL` parce que ce script tourne
# hors navigateur, exactement comme un composant serveur de Next -- c'est la
# branche « serveur » de resolveBaseUrl() qui est ainsi exercee.
API_INTERNAL_URL="${API_INTERNAL_URL:-http://localhost:8000}"
export API_INTERNAL_URL

# La sonde de vie AVANT tout le reste : sans elle, une pile eteinte se
# manifesterait par trois echecs de controle, et le lecteur chercherait la
# panne dans le client genere.
if ! curl --silent --fail --max-time 5 "$API_INTERNAL_URL/health/live" >/dev/null 2>&1; then
  echo "SHARED-03 : l API ne repond pas sur $API_INTERNAL_URL." >&2
  echo "            Demarrer la pile d abord :  make dev" >&2
  exit 1
fi

# Le dossier de compilation ne survit pas au script, quel que soit le sort de
# la verification.
trap 'rm -rf "$BUILD_DIR"' EXIT

echo "SHARED-03 : compilation jetable du client genere..."
pnpm --filter @repo/api-client exec tsc -p tsconfig.verify.json

# Le package est en `"type": "module"` : sans ce marqueur, Node lirait la sortie
# CommonJS de tsc comme de l'ESM et echouerait sur « exports is not defined ».
# Un package.json de deux lignes au sommet du dossier compile suffit a
# rebasculer cette branche de l'arborescence, et lui seul.
echo '{ "type": "commonjs" }' >"$BUILD_DIR/package.json"

node "$BUILD_DIR/scripts/verify.js"
