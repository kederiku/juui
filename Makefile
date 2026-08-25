# Orchestration du poste de developpement (INFRA-06).
#
# CE FICHIER N'EXECUTE PRESQUE RIEN LUI-MEME
# Il nomme des commandes qui existent deja ailleurs -- `docker compose`, les
# cibles de backend/api/Makefile, les scripts pnpm de la racine -- et les rend
# memorisables. Une recette qui tient en une ligne reste ecrite ici, ou elle se
# lit ; deux cibles seulement ont demande un fichier dans scripts/, chacune
# pour une raison ecrite en tete du sien.
#
# L'INVOCATION DE COMPOSE EST CELLE DES DEUX VARIABLES CI-DESSOUS, ET AUCUNE AUTRE
# Le fichier compose vit dans docker/, le .env a la RACINE : sans
# `--project-directory .`, toutes les `${...}` du fichier compose vaudraient la
# chaine vide, SANS la moindre erreur. Et des qu'un `-f` est passe, l'override
# de developpement n'est PLUS charge tout seul : il faut le nommer. D'ou `up`
# et `dev`, les deux cibles distinctes annoncees par le README.
#
# LE .env N'EST PAS LU ICI, ET C'EST VOULU
# `include .env` suivi de `export` mettrait POSTGRES_HOST=postgres dans
# l'environnement de CHAQUE recette. Les cibles db-*, qui tournent sur l'HOTE,
# chercheraient alors un hote `postgres` introuvable : pydantic-settings donne
# la priorite aux variables du processus sur backend/api/.env, ou POSTGRES_HOST
# vaut `localhost`. Les mots de passe et la clef JWT partiraient au passage
# dans tout sous-processus, pnpm compris. `docker compose` lit ce fichier
# lui-meme ; la seule cible qui a besoin d'une valeur -- `mail`, pour son
# port -- la lit dans son script, et cette valeur seule.
#
# CONVENTIONS : celles de backend/api/Makefile, qui les adopte depuis BACK-02 --
# `help` par defaut et en tete, un unique .PHONY, une description apres `##`
# sur chaque cible, que `make help` extrait. Compatible make 3.81 (celui des
# Command Line Tools d'Apple) : pas de .ONESHELL, chaque ligne de recette est
# un shell distinct.

# `help` doit rester la premiere cible declaree : c'est ce que `make` nu lance.
.DEFAULT_GOAL := help

# `--project-directory .` deplace AUSSI la resolution des chemins montes, qui
# partent donc de la racine et non de docker/ -- voir l'en-tete du fichier
# compose.
COMPOSE := docker compose --project-directory . -f docker/docker-compose.yml

# Le second `-f` est le SEUL moyen de charger l'override : Compose l'ignore
# silencieusement des qu'un fichier lui est nomme.
COMPOSE_DEV := $(COMPOSE) -f docker/docker-compose.override.yml

.PHONY: help up dev down restart logs shell-api mail \
	db-migrate db-upgrade db-downgrade db-reset seed \
	lint format typecheck test test-back test-front

help: ## Affiche cette aide
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-13s\033[0m %s\n", $$1, $$2}'

# -----------------------------------------------------------------------------
# Pile conteneurisee
# -----------------------------------------------------------------------------

# La garde .env n'est pas du zele : sans le fichier, Compose substituerait la
# chaine vide dans chaque `${...}` SANS erreur -- postgres sans mot de passe,
# ports invalides. On refuse avec la commande a taper, plutot que de copier le
# gabarit en douce : la sequence d'installation du README reste la seule.
up: ## Demarre toute la pile en arriere-plan, sur les images servies
	@test -f .env || { echo 'INFRA-06 : .env absent -- le creer d abord : cp .env.example .env'; exit 1; }
	$(COMPOSE) up -d

# La meme pile sur le CODE DU POSTE. `--build` n'est pas decoratif : la cible
# de build change d'un mode a l'autre (`dev` partout), et sans lui compose
# repartirait sur l'image servie deja construite.
dev: ## Demarre la pile en mode developpement (code monte, rechargement a chaud)
	@test -f .env || { echo 'INFRA-06 : .env absent -- le creer d abord : cp .env.example .env'; exit 1; }
	$(COMPOSE_DEV) up -d --build

down: ## Arrete la pile et libere les ports (les volumes survivent)
	$(COMPOSE) down

# Ne recree AUCUN conteneur : chacun garde le mode -- servi ou developpement --
# et l'environnement avec lesquels il a ete cree. Apres un changement de .env,
# rejouer `make up` ou `make dev`, qui recreent ce qui a change.
restart: ## Redemarre les conteneurs sans les recreer
	$(COMPOSE) restart

# Meme garde de parametre que le m= de backend/api/Makefile : le message
# enseigne la syntaxe. La validation du nom n'est pas du zele non plus :
# `compose logs --follow` sur un service inconnu n'affiche RIEN et sort en 0 --
# un ecran vide a regarder indefiniment. `--profile '*'` : sans lui,
# redisinsight (profil tools) manquerait a la liste.
#
# `--tail 100` : sans lui, compose rejoue l'integralite du journal avant de
# suivre.
logs: ## Suit les journaux d'un service (service=api)
	@test -n "$(service)" || { echo 'Usage : make logs service=api'; exit 1; }
	@$(COMPOSE) --profile '*' config --services | grep -qx "$(service)" \
		|| { echo "INFRA-06 : aucun service nomme $(service). Services declares :"; \
		$(COMPOSE) --profile '*' config --services | sort | sed 's/^/  - /'; exit 1; }
	$(COMPOSE) logs --follow --tail 100 $(service)

# `bash` et non `sh` : l'image d'API est batie sur python:3.14-slim, une
# Debian, qui l'embarque. Ni curl ni wget dans l'image ; USER juui, WORKDIR
# /app.
shell-api: ## Ouvre un shell dans le conteneur d'API
	$(COMPOSE) exec api bash

mail: ## Ouvre la boite de reception Mailpit dans le navigateur
	@sh scripts/open-mailbox.sh

# -----------------------------------------------------------------------------
# Base de donnees
# -----------------------------------------------------------------------------
# LES CIBLES db-* TOURNENT SUR L'HOTE, jamais dans un conteneur, et deleguent a
# backend/api/Makefile qui les porte depuis BACK-07. Deux raisons :
#   - `alembic revision --autogenerate` declenche les post_write_hooks (Ruff),
#     absent des images `prod` et `worker` ;
#   - l'entrypoint des conteneurs joue deja `alembic upgrade head` a chaque
#     demarrage, il n'y a rien a lui redire.
# Prerequis : `uv` sur le poste, le port PostgreSQL publie, et backend/api/.env
# qui pointe POSTGRES_HOST=localhost.

db-migrate: ## Genere une migration autogeneree -- A RELIRE (m="message")
	@test -n "$(m)" || { echo 'Usage : make db-migrate m="message de la revision"'; exit 1; }
	$(MAKE) --no-print-directory -C backend/api migration m="$(m)"

db-upgrade: ## Applique les migrations jusqu'a head
	$(MAKE) --no-print-directory -C backend/api migrate

# Un cran a la fois, jamais `base` : la regle est celle de backend/api/Makefile.
db-downgrade: ## Annule la derniere migration appliquee
	$(MAKE) --no-print-directory -C backend/api downgrade

# La sequence se lit ICI plutot que dans le script : celui-ci s'arrete a ce que
# Docker seul sait faire -- detruire et recreer le volume --, les deux etapes
# suivantes sont des cibles qui existent deja. `force=1` saute la confirmation.
db-reset: ## Detruit le volume de la base, la recree, migre et injecte le seed (force=1)
	@COMPOSE="$(COMPOSE)" force="$(force)" sh scripts/reset-database.sh
	@$(MAKE) --no-print-directory db-upgrade
	@$(MAKE) --no-print-directory seed

# Declaree sans etre fournie, ce que la carte d'INFRA-08 demande explicitement.
# Sortie 0 : db-reset l'enchaine, et un echec ici ferait passer pour ratee une
# remise a zero qui a reussi.
seed: ## Injecte le jeu de donnees de demonstration (INFRA-08)
	@echo 'INFRA-06 : aucun jeu de donnees a injecter -- le seed arrive avec INFRA-08.'

# -----------------------------------------------------------------------------
# Qualite -- backend PUIS frontend
# -----------------------------------------------------------------------------
# Le backend d'abord : c'est la chaine la moins chere, meme raisonnement que le
# `lint` de backend/api/Makefile qui passe Ruff avant les contrats d'imports.
# Cote pnpm, `lint` et `format` parcourent le depot en UNE passe depuis la
# racine : c'est une regle du depot (site de documentation, page « Makefile et
# scripts de la racine ») -- deleguer
# aux workspaces laisserait de cote les fichiers de la racine.

lint: ## Analyse statique du backend (Ruff, contrats) puis du depot (ESLint)
	$(MAKE) --no-print-directory -C backend/api lint
	pnpm lint

format: ## Reformate le backend (Ruff) puis tout le depot (Prettier)
	$(MAKE) --no-print-directory -C backend/api format
	pnpm format

typecheck: ## Verifie le typage Python (mypy strict) puis TypeScript
	$(MAKE) --no-print-directory -C backend/api typecheck
	pnpm typecheck

# AUCUNE SUITE N'EXISTE ENCORE : le harnais pytest arrive avec BACK-12, celui
# des workspaces avec QA-02. La cible backend est declaree quand meme -- c'est
# l'interface que le ticket annonce -- et sort en 0 en nommant ce qu'on attend,
# comme l'entrypoint d'INFRA-04 le fait pour les migrations absentes.
test-back: ## Suites de tests du backend (BACK-12)
	@echo 'INFRA-06 : aucune suite backend -- le harnais pytest arrive avec BACK-12.'

# Celle-ci est un VRAI appel : `pnpm -r --if-present run test` ignore en
# silence les workspaces sans script `test`, donc tous aujourd'hui. Le jour ou
# QA-02 en declare un, cette cible marche sans etre touchee.
test-front: ## Suites de tests des workspaces pnpm (QA-02)
	pnpm test
	@echo 'INFRA-06 : les workspaces sans script test ont ete ignores (--if-present).'

test: test-back test-front ## Enchaine les suites backend et frontend
