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
	generate-api generate-api-check verify-api-client \
	lint format typecheck test test-back test-front

help: ## Affiche cette aide
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

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
# Contrat d'API et client genere (SHARED-03)
# -----------------------------------------------------------------------------
# BACKEND PUIS FRONTEND, comme les cibles de qualite ci-dessous -- mais ici
# l'ordre n'est pas une preference : la seconde etape LIT le fichier que la
# premiere ecrit.
#
# `pnpm generate:api` seul reste utile, et c'est voulu : il regenere le client
# depuis l'openapi.json COMMITE, sans `uv` sur le poste -- de quoi corriger un
# reglage d'Orval ou le mutator. Ce qu'il ne fait pas, c'est VOIR un changement
# de contrat : pour cela il faut reexporter, donc cette cible-ci. C'est ELLE,
# l'etape obligatoire apres toute modification d'un contrat d'API.
generate-api: ## Exporte le schema OpenAPI puis regenere le client (SHARED-03)
	$(MAKE) --no-print-directory -C backend/api openapi
	pnpm generate:api

# LE PENDANT LOCAL DE LA CI, meme esprit que le `migrate-check` de
# backend/api/Makefile : .github/workflows/api-client.yml ne lance rien d'autre
# que cette cible, si bien qu'un echec de CI se reproduit ici sans deviner.
#
# `git add --intent-to-add` AVANT le diff, et ce n'est pas du zele : `git diff`
# ne voit QUE les fichiers suivis. Une regeneration qui cree un fichier neuf --
# une etiquette OpenAPI de plus, donc un fichier Orval de plus -- passerait
# inapercue, et la CI validerait un client incomplet. Sur un fichier deja suivi
# l'operation ne fait rien : en regime etabli, cette ligne est un no-op.
#
# `--exit-code` AFFICHE le patch en plus de sortir en 1 : le diff est la
# premiere moitie du message d'erreur, le bloc `||` en est la seconde.
#
# Le pathspec borne la verification a ce que la chaine ecrit. C'est la raison
# pour laquelle openapi.json vit dans ce dossier (ADR-0019) : le contrat et sa
# traduction tiennent dans un seul chemin.
generate-api-check: generate-api ## Echoue si le client genere ne correspond plus au contrat
	@git add --intent-to-add -- packages/api-client
	@git --no-pager diff --exit-code -- packages/api-client \
		|| { echo ''; \
		echo 'SHARED-03 : le client d API ne correspond plus au contrat OpenAPI.'; \
		echo 'Le diff ci-dessus est ce que la regeneration vient de produire, et'; \
		echo 'qui n est pas commite.'; \
		echo ''; \
		echo 'Deux causes, un seul geste :'; \
		echo '  - un contrat d API a change : ce diff est ATTENDU, il appartient'; \
		echo '    a la meme pull request que le changement de contrat ;'; \
		echo '  - packages/api-client/src/generated/ a ete edite a la main :'; \
		echo '    ADR-0007 interdit cette edition, la regeneration l a perdue.'; \
		echo ''; \
		echo 'Sur le poste :'; \
		echo '    make generate-api'; \
		echo '    git add packages/api-client'; \
		echo ''; \
		exit 1; }

# La preuve du critere « un hook genere appelle reellement l API » (SHARED-03).
# Exige la pile demarree (`make dev`) : elle appelle le VRAI backend, pas un
# double. Hors CI pour cette raison meme -- le workflow n'a pas de service a
# interroger, il se borne a verifier que le genere est a jour.
verify-api-client: ## Appelle l API avec le client genere (pile demarree)
	@sh scripts/verify-api-client.sh

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

# Delegue a backend/api/Makefile, qui porte une vraie cible `test` depuis
# BACK-06b. Meme prerequis qu'elle : PostgreSQL docker demarre (`make dev`),
# les tests d'isolation travaillent sur la base `app_test` d'INFRA-01. Le
# decoupage par niveaux (unit/integration/slow) arrive avec BACK-12.
test-back: ## Suite de tests du backend (PostgreSQL docker demarre)
	$(MAKE) --no-print-directory -C backend/api test

# Celle-ci est un VRAI appel : `pnpm -r --if-present run test` ignore en
# silence les workspaces sans script `test`. FRONT-04 a ete le premier a en
# declarer un -- packages/api-client, qui prouve hors ligne la portee de ses
# clefs de cache, et depuis FRONT-10 la traduction des erreurs -- et la cible
# n'a pas eu a bouger, comme annonce. QA-02 n'aura pas davantage a la toucher.
test-front: ## Suites de tests des workspaces pnpm (QA-02)
	pnpm test
	@echo 'INFRA-06 : les workspaces sans script test ont ete ignores (--if-present).'

test: test-back test-front ## Enchaine les suites backend et frontend
