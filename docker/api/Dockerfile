# syntax=docker/dockerfile:1

# Image du service d'API (INFRA-04, consommee par INFRA-05b et QA-03).
#
# Six etages, trois cibles utiles : `dev`, `prod` et `worker`. Les trois autres
# -- `uv`, `base`, `builder`, `runtime` -- ne sont que des paliers partages.
#
# POURQUOI CE FICHIER N'EST PAS DANS backend/api/
# Le depot range les configurations de conteneurisation dans docker/, un dossier
# par service : docker/postgres/, docker/redis/, docker/minio/, et maintenant
# docker/api/. Le .dockerignore, lui, DOIT vivre dans backend/api/ -- Docker ne
# lit qu'un seul fichier d'exclusion, `<contexte>/.dockerignore`, et le contexte
# de build est backend/api.
#
# CONSEQUENCE : L'ENTRYPOINT N'EST PAS DANS LE CONTEXTE
# entrypoint.sh est a cote de ce fichier, donc HORS du contexte backend/api :
# un `COPY entrypoint.sh` echouerait. D'ou le CONTEXTE ADDITIONNEL nomme
# `scripts`, declare par le fichier compose et repris par le `COPY --from=scripts`
# de l'etage `runtime`. Un build hors compose doit donc le passer a la main :
#
#   docker build --target prod \
#     --build-context scripts=docker/api \
#     -f docker/api/Dockerfile backend/api
#
# Les deux autres pistes ont ete ecartees : prendre la RACINE pour contexte
# enverrait node_modules entier au demon et deplacerait le .dockerignore hors de
# la portee du ticket ; monter l'entrypoint en volume, comme le fait INFRA-02
# pour redis.conf, rendrait l'image non autonome -- or QA-03 la publie dans un
# registre, ou aucun volume ne la suivra.
#
# CE QUE CE FICHIER NE FAIT PAS
# Aucun HEALTHCHECK : le depot declare toutes ses sondes dans le fichier
# compose, depuis INFRA-01. Celle du service `api` s'y trouve.

# Version de uv, EPINGLEE. Les binaires viennent de l'image officielle, jamais
# d'un pip install : c'est une exigence du ticket, et c'est aussi ce qui rend le
# build reproductible.
#
# 0.11.7 a l'origine, montee a 0.12.5 pour aligner les trois environnements qui
# lancent uv -- celui-ci, la CI (`version:` de setup-uv dans ci-backend.yml) et
# le poste. Ils avaient derive, et l'ecart ne se voyait que dans un
# avertissement de log. Le `required-version` de backend/api/pyproject.toml le
# fera desormais ECHOUER : si cet ARG sort de la plage qu'il declare, c'est le
# `uv sync` de l'etage `builder` qui s'arrete, et le `docker build` avec lui --
# au bon moment pour l'apprendre, comme pour PYTHON_VERSION juste en dessous.
#
# Les 22 ruptures de uv 0.12 ont ete relues contre ce que ce fichier fait
# reellement : aucune ne s'applique. Les deux qui meritaient un regard sont
# « require --force before clearing a directory that is not a virtual
# environment » -- /opt/venv est cree de zero par le premier `uv sync`, les
# suivants retrouvent un vrai venv -- et le rejet des sdists qui ne sont pas en
# .tar.gz, sans objet ici puisque le lock n'installe que des roues.
ARG UV_VERSION=0.12.5

# Alignee sur backend/api/.python-version et sur le `requires-python = "==3.14.*"`
# de uv.lock. Les faire diverger ferait echouer `uv sync --frozen` a la
# construction -- ce qui est le bon moment pour l'apprendre.
ARG PYTHON_VERSION=3.14

# Distribution Debian NOMMEE plutot que le `-slim` nu. Sans elle, une bascule de
# Debian cote amont changerait la libc et les paquets systeme de l'image d'un
# `docker build` a l'autre, sans qu'aucune ligne du depot n'ait bouge.
ARG DEBIAN_RELEASE=trixie


# =============================================================================
# uv -- source des binaires
# =============================================================================
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv


# =============================================================================
# base -- socle commun a tous les etages
# =============================================================================
FROM python:${PYTHON_VERSION}-slim-${DEBIAN_RELEASE} AS base

# L'ENVIRONNEMENT VIRTUEL VIT HORS DE /app, ET C'EST LE POINT LE PLUS IMPORTANT
# DE CE FICHIER. La cible `dev` tourne avec le code MONTE EN VOLUME sur /app
# (INFRA-05b). Un .venv laisse dans /app serait alors MASQUE par ce montage :
# le conteneur demarrerait sur un environnement vide, avec un « ModuleNotFoundError:
# fastapi » sans aucun rapport visible avec sa cause. /opt/venv est hors d'atteinte
# du montage.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    \
    # L'interpreteur est celui de l'image de base : uv ne doit pas en telecharger
    # un second, qui ferait grossir l'image d'une centaine de mega-octets pour
    # rien.
    UV_PYTHON_DOWNLOADS=0 \
    \
    # Le lien physique echoue entre le cache monte (un autre systeme de fichiers)
    # et la couche en cours d'ecriture. uv le signale et bascule tout seul, mais
    # en journalisant un avertissement a chaque build.
    UV_LINK_MODE=copy \
    \
    # Precompile les .pyc a l'installation plutot qu'au premier import : c'est
    # une seconde ou deux gagnees a chaque demarrage de conteneur, et cela compte
    # pour un service qu'on redemarre souvent.
    UV_COMPILE_BYTECODE=1 \
    \
    # Interdit d'ecrire des .pyc a l'EXECUTION. Sans cela, le processus non-root
    # de la cible `dev` tenterait d'en ecrire dans le code monte depuis l'hote --
    # au mieux des __pycache__ parasites dans l'arbre de travail, au pire une
    # erreur de permission.
    PYTHONDONTWRITEBYTECODE=1 \
    \
    # Sortie non tamponnee : sans elle, les premieres lignes de journal restent
    # bloquees dans le tampon et `docker compose logs api` semble muet pendant
    # le demarrage.
    PYTHONUNBUFFERED=1

WORKDIR /app

# Utilisateur non-root, cree ici pour que TOUS les etages partagent le meme
# uid/gid -- ce qui evite un `chown` recursif sur le virtualenv d'un etage a
# l'autre, et la couche de plusieurs centaines de mega-octets qui va avec.
#
# `--no-create-home` : ce compte ne sert qu'a executer un processus, il n'a
# aucun fichier a lui. `--system` lui donne un uid hors de la plage des comptes
# humains, mais on fixe quand meme 1001 explicitement : une image dont l'uid
# change au fil des reconstructions rendrait imprevisibles les droits sur les
# volumes montes.
RUN groupadd --system --gid 1001 juui \
    && useradd --system --uid 1001 --gid juui --no-create-home --shell /usr/sbin/nologin juui


# =============================================================================
# builder -- resolution et installation des dependances
# =============================================================================
FROM base AS builder

COPY --from=uv /uv /uvx /bin/

# COUCHE 1 -- LES DEPENDANCES SEULES.
#
# C'est l'ordonnancement qui satisfait le critere « un changement de code seul ne
# reinstalle pas les dependances ». Les trois fichiers sont MONTES le temps de la
# commande plutot que copies : rien d'eux ne subsiste dans la couche, dont
# l'empreinte ne depend donc que de leur contenu.
#
# `--no-install-project` est ce qui separe reellement les deux couches : sans
# lui, uv installerait aussi `juui-api`, et la moindre modification de src/
# invaliderait l'installation de fastapi, sqlalchemy et boto3 avec elle.
#
# README.md doit etre monte : pyproject.toml declare `readme = "README.md"`, et
# le backend de build uv_build lit ce fichier pour composer les metadonnees du
# paquet. C'est aussi ce qui explique le `!README.md` du .dockerignore.
#
# `--frozen` interdit toute re-resolution : si uv.lock ne correspond plus au
# pyproject.toml, le build ECHOUE au lieu de fabriquer en silence une image qui
# ne contient pas les versions verrouillees.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=README.md,target=README.md \
    uv sync --frozen --no-dev --no-install-project --no-editable

# COUCHE 2 -- LE CODE APPLICATIF.
# Ce que le contexte contient encore apres le .dockerignore : src/, pyproject.toml,
# uv.lock, README.md, le Makefile, .python-version. Et, depuis BACK-07,
# alembic.ini et le dossier de migrations -- entres sans qu'on ait eu a revenir
# sur ce fichier.
COPY . /app

# `--no-editable` installe le paquet POUR DE VRAI dans /opt/venv, au lieu d'y
# poser un pointeur vers /app/src. C'est ce qui rend le virtualenv autonome :
# l'etage `runtime` n'a plus besoin de /app pour importer `app.main`.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable


# =============================================================================
# runtime -- socle des images executables (sans commande)
# =============================================================================
# Etage intermediaire volontaire : `prod` et `worker` n'en different que par leur
# CMD. Tout ce qui les precede est donc ecrit, et construit, UNE SEULE FOIS.
FROM base AS runtime

# Le virtualenv, avec le code applicatif deja dedans (voir `--no-editable`).
COPY --from=builder /opt/venv /opt/venv

# Le code source, en plus du virtualenv, comme le demande le ticket. Il ne sert
# pas aux imports -- ceux-ci passent par /opt/venv -- mais il porte ce qui vit a
# COTE du paquet : alembic.ini et les migrations, livres par BACK-07, que
# l'entrypoint ci-dessous cherche dans ce repertoire de travail.
COPY --from=builder /app /app

# Contexte de build ADDITIONNEL, declare par le fichier compose. Voir l'en-tete.
COPY --from=scripts --chmod=0755 entrypoint.sh /usr/local/bin/entrypoint.sh

# Hotes dont uvicorn accepte les en-tetes X-Forwarded-*. C'est deja son defaut ;
# l'ecrire rend le reglage VISIBLE dans `docker image inspect` et surchargeable
# depuis le fichier compose. Le remplacer par `*` laisserait n'importe quel
# client s'annoncer sous l'IP de son choix -- et contourner la limitation par IP
# prevue en BACK-17. Ce qu'il faut y mettre est explique dans .env.example.
ENV FORWARDED_ALLOW_IPS=127.0.0.1

# NI /app NI /opt/venv N'APPARTIENNENT A `juui`, ET C'EST VOULU. Les deux sont
# lisibles par tous et n'appartiennent qu'a root : le processus execute son
# propre code sans pouvoir le reecrire. Un `--chown` aurait par ailleurs
# recopie tout le virtualenv dans une couche supplementaire.
USER juui

EXPOSE 8000

# Attend PostgreSQL, applique les migrations, puis `exec` la commande de l'image.
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]


# =============================================================================
# dev -- rechargement a chaud, code monte en volume
# =============================================================================
# Ne descend PAS de `runtime` : cette cible a besoin du groupe `dev` (Ruff, Mypy,
# Pytest) et d'une installation EDITABLE, deux choses que le ticket exclut
# explicitement de l'image de production.
FROM base AS dev

# uv reste dans l'image : `docker compose exec api uv run ruff check .` doit
# fonctionner sans reconstruire quoi que ce soit.
COPY --from=uv /uv /uvx /bin/

# Meme decoupage en deux couches que `builder`, et pour la meme raison. Sans
# `--no-dev` cette fois : c'est tout l'objet de cette cible.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=README.md,target=README.md \
    uv sync --frozen --no-install-project

COPY . /app

# EDITABLE, contrairement a `builder` : le paquet installe n'est qu'un pointeur
# vers /app/src. Le montage du code par INFRA-05b remplace alors reellement ce
# que le conteneur execute -- c'est ce qui rend le rechargement a chaud utile.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen

COPY --from=scripts --chmod=0755 entrypoint.sh /usr/local/bin/entrypoint.sh

ENV FORWARDED_ALLOW_IPS=127.0.0.1

USER juui

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

# `--reload-dir` limite la surveillance a src/ : sans lui, watchfiles inspecte
# tout /app, y compris les caches d'outillage que le montage de volume ramene
# depuis l'hote, et redemarre le serveur a chaque passage de Ruff.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--reload", \
     "--reload-dir", "/app/src", \
     "--proxy-headers"]


# =============================================================================
# worker -- meme image, autre commande (declaree en service par INFRA-05b)
# =============================================================================
# ATTENTION : cette cible SE CONSTRUIT aujourd'hui, mais ne TOURNE pas encore --
# le module de broker qu'elle designe est ecrit par BACK-15. Le ticket ne demande
# que la construction, et c'est ce que verifie son critere d'acceptation.
#
# CE QU'IL SE PASSE SI ON LA LANCE QUAND MEME, verifie : le conteneur ne s'arrete
# PAS. Le gestionnaire de processus de taskiq voit ses workers mourir sur un
# « ModuleNotFoundError: No module named 'app.shared.infrastructure.tasks' », et
# les relance en boucle. Le conteneur reste donc `running` et `docker compose ps`
# le montre en bonne sante alors qu'il ne consomme aucune tache. INFRA-05b, qui
# declare le service, doit le savoir : seuls les journaux disent la verite tant
# que BACK-15 n'a pas livre le broker.
FROM runtime AS worker

# `--no-configure-logging` : sans lui, le `basicConfig` de TaskIQ court AVANT
# l'import du broker, donc avant que `worker_startup` n'appelle
# `configure_logging` (BACK-11), et poserait un second handler sur la racine --
# chaque ligne du worker sortirait en double, dont une au mauvais format.
CMD ["taskiq", "worker", "--no-configure-logging", \
     "app.shared.infrastructure.tasks.broker:broker"]


# =============================================================================
# prod -- image servie, DERNIER ETAGE DU FICHIER
# =============================================================================
# Sa position n'est pas esthetique : Docker construit le DERNIER etage quand
# aucun `--target` n'est passe. Mettre `worker` ici ferait produire l'image du
# worker a un `docker build` nu -- une erreur silencieuse et difficile a voir.
FROM runtime AS prod

# Forme `exec` : aucune interpolation de variable n'y a lieu. Le nombre de
# processus et les hotes de confiance ne sont donc PAS des arguments -- uvicorn
# lit lui-meme WEB_CONCURRENCY et FORWARDED_ALLOW_IPS (config.py, lignes 352 et
# 357 de la version 0.52). S'appuyer sur les variables qu'il connait deja evite
# un `sh -c` autour de la commande, et une seconde source de verite a cote du
# .env.
#
# `--proxy-headers` est deja le defaut depuis uvicorn 0.30 ; il est ecrit parce
# que le ticket en fait un critere d'acceptation, et parce qu'un defaut peut
# changer.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--proxy-headers"]
