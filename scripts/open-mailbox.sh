#!/bin/sh
# Ouverture de la boite de reception Mailpit (INFRA-06 ; service livre par
# INFRA-07).
#
# POURQUOI UN FICHIER PLUTOT QU'UNE RECETTE EN LIGNE
# Deux choses qu'une ligne de Makefile ne sait pas faire proprement, et que
# make 3.81 interdit d'ecrire sur plusieurs lignes -- il n'a pas de .ONESHELL,
# chaque ligne de recette etant un shell distinct :
#   1. choisir l'ouvreur d'URL du poste, et se rabattre sur un simple
#      affichage quand il n'y en a aucun (poste sans environnement graphique,
#      session SSH) ;
#   2. lire UNE variable du .env de la racine sans l'exporter dans
#      l'environnement de make -- la mise en garde est en tete du Makefile.
#
# LE CHOIX DE L'OUVREUR SE FAIT PAR SYSTEME, JAMAIS PAR DISPONIBILITE
# Sur plusieurs distributions Linux, /usr/bin/open existe (util-linux) et
# BASCULE DE CONSOLE VIRTUELLE : un « premier trouve parmi open, xdg-open »
# ferait sauter l'ecran d'un poste Linux. D'ou le `case` sur `uname -s`.
#
# VARIABLE LUE
# MAILPIT_WEB_HOST_PORT, documentee dans .env.example. C'est le port PUBLIE
# sur le poste ; MAILPIT_WEB_PORT est celui du conteneur, qu'aucun navigateur
# ne joint.
#
# CE SCRIPT NE PARLE PAS A DOCKER : un navigateur ouvert sur une pile eteinte
# le dit tout seul, et interroger `docker` pour ouvrir une URL ajouterait une
# dependance sans rien fiabiliser.
set -e

ENV_FILE=".env"

# L'environnement du shell appelant l'emporte sur le fichier, comme dans
# `docker compose` lui-meme.
PORT="${MAILPIT_WEB_HOST_PORT:-}"

if [ -z "$PORT" ] && [ -f "$ENV_FILE" ]; then
  # UNE seule variable est extraite, et par du texte : `. .env` sourcerait
  # tout le fichier -- mots de passe et clef JWT compris -- dans ce shell.
  # L'extraction est sure parce que .env.example impose ses valeurs sans
  # guillemets, sans espace et sans commentaire de fin de ligne.
  #
  # `tail -n 1` : la derniere affectation gagne, comme dans un dotenv.
  PORT=$(sed -n 's/^[[:space:]]*MAILPIT_WEB_HOST_PORT=//p' "$ENV_FILE" | tail -n 1)
fi

# Le repli est la valeur de .env.example et du tableau des ports du site de
# documentation. Il
# sert au depot fraichement clone, ou le .env n'existe pas encore.
if [ -z "$PORT" ]; then
  echo "INFRA-06 : MAILPIT_WEB_HOST_PORT introuvable (.env absent ?) -- repli sur 8025." >&2
  PORT=8025
fi

URL="http://localhost:$PORT"

# L'URL est affichee AVANT toute tentative : quoi qu'il arrive ensuite,
# l'utilisateur l'a sous les yeux.
echo "INFRA-06 : boite de reception Mailpit -- $URL"

case "$(uname -s)" in
  Darwin)
    OPENERS="open"
    ;;
  Linux)
    if [ -n "${WSL_DISTRO_NAME:-}" ] || grep -qi microsoft /proc/version 2>/dev/null; then
      # wslu fournit wslview, qui passe la main au navigateur de Windows.
      OPENERS="wslview xdg-open"
    elif [ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
      # Pas de serveur d'affichage : rien a tenter, l'URL est deja affichee.
      echo "INFRA-06 : pas d'environnement graphique -- ouvrir l'URL a la main."
      exit 0
    else
      OPENERS="xdg-open"
    fi
    ;;
  *)
    OPENERS="xdg-open"
    ;;
esac

# `command -v` et non `which` : le premier est POSIX, le second ne l'est pas.
for opener in $OPENERS; do
  if command -v "$opener" >/dev/null 2>&1; then
    exec "$opener" "$URL"
  fi
done

echo "INFRA-06 : aucun ouvreur d'URL sur ce poste ($OPENERS) -- ouvrir l'URL a la main."
exit 0
