# Commandes de qualite du service d'API (BACK-02) et de migration (BACK-07).
#
# uv n'a pas de lanceur de taches -- pas de [tool.uv.scripts], pas d'equivalent
# aux scripts npm : ce Makefile est le seul endroit ou ces commandes portent un
# nom. Il adopte d'avance les conventions d'INFRA-06 (cibles .PHONY, aide par
# defaut auto-documentee par extraction des commentaires `##`), pour que le
# Makefile racine n'ait plus qu'a deleguer ici.
#
# Tout passe par `uv run` : l'environnement se synchronise a la demande, il n'y
# a jamais a activer .venv soi-meme.

# `help` doit rester la premiere cible declaree : c'est ce que `make` nu lance.
.DEFAULT_GOAL := help

.PHONY: help lint lint-fix imports format format-check typecheck check test \
	test-unit test-integration test-tenancy test-cov \
	migration migrate downgrade history migrate-check openapi

# Les deux couches que le seuil de couverture garde. Une seule declaration, lue
# par `test-cov`. Le double `**` traverse les separateurs, ce qui est necessaire :
# la couche `domain` vit a deux profondeurs -- `app/shared/domain/ports/cache.py`
# et `app/modules/identity/domain/entities.py`.
COVERED_LAYERS := */app/**/domain/*,*/app/**/application/*

help: ## Affiche cette aide
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-13s\033[0m %s\n", $$1, $$2}'

# Les deux verifications sont ecrites a la suite plutot que declarees en
# prerequis (`lint: imports`) : un prerequis s'executerait AVANT Ruff, alors
# qu'on veut voir echouer la verification la moins chere en premier.
lint: ## Signale les infractions aux regles Ruff et aux contrats d'architecture
	uv run ruff check .
	uv run lint-imports

lint-fix: ## Corrige ce que Ruff sait corriger sans risque
	uv run ruff check --fix .

# Les contrats d'architecture de BACK-04b : purete du domaine, sens des
# couches, independance des modules. Ils sont declares dans pyproject.toml, ou
# chacun porte sa justification. Rien a corriger automatiquement ici -- une
# violation se resout en deplacant du code, pas en reecrivant un import.
imports: ## Verifie les contrats d'architecture (import-linter)
	uv run lint-imports

format: ## Reformate le code (et les blocs Python de la documentation)
	uv run ruff format .

format-check: ## Verifie le formatage sans rien reecrire
	uv run ruff format --check .

typecheck: ## Verifie le typage en mode strict
	uv run mypy src alembic scripts

# QUATRE CIBLES, ET L'AXE QUI LES SEPARE EST LE SERVICE, PAS LA COUCHE. Le
# marqueur `integration` est pose automatiquement sur tout test dont la cloture
# de fixtures atteint un service reel (voir tests/conftest.py) : rien ne se tient
# a la main, rien ne peut mentir.
test: ## Lance toute la suite (pile docker demarree)
	uv run pytest

# LA CIBLE SANS DOCKER, et c'est le critere 7 du ticket. Domaine, cas d'usage sur
# doublures, moities en memoire des suites de conformite : rien de tout cela ne
# demande la fixture `engine`, donc rien ne cherche a joindre PostgreSQL.
# `not slow` en plus : cette cible se lance en boucle, elle doit rendre la main.
test-unit: ## Les tests qui ne touchent aucun service -- sans docker
	uv run pytest -m "unit and not slow"

# Un service absent fait SAUTER ses tests et le dit en fin d'execution.
# `--require-services` transforme le saut en echec : c'est le drapeau de la CI,
# celui qui fait d'une execution verte une preuve (QA-01).
test-integration: ## Les seuls tests adosses a un service reel
	uv run pytest -m integration

# LA CATEGORIE OBLIGATOIRE (BACK-12) : la seule preuve que l'isolation entre
# groupes tient. `--strict-markers` etant actif, une faute de frappe sur le
# marqueur casse la collecte au lieu de vider silencieusement la selection.
test-tenancy: ## Les tests d'isolation multi-tenant
	uv run pytest -m tenant_isolation

# DEUX RAPPORTS, ET UN SEUL SEUIL. Le premier montre le service entier sans le
# juger ; le second garde `domain/` et `application/`, les deux couches dont le
# comportement est le sujet des tests. Le seuil est celui du ticket. Exige la
# pile complete : un taux mesure sur une pile partielle n'est pas comparable.
test-cov: ## Suite complete + couverture, seuil bloquant sur domain/ et application/
	uv run pytest --cov=app --cov-report=
	@echo '--- Couverture du service (informatif) ---'
	uv run coverage report
	@echo '--- Couverture gardee : domain/ et application/ ---'
	uv run coverage report --include='$(COVERED_LAYERS)' --fail-under=80

# Migrations Alembic (BACK-07). Le message devient le slug du fichier ET la
# premiere ligne de sa docstring : francais sans accents, sans point final,
# moins de 40 caracteres.
migration: ## Genere une migration autogeneree -- A RELIRE (m="message")
	@test -n "$(m)" || { echo 'Usage : make migration m="message de la revision"'; exit 1; }
	uv run alembic revision --autogenerate -m "$(m)"

migrate: ## Applique les migrations jusqu'a head
	uv run alembic upgrade head

# Un cran a la fois, jamais `base` : revenir a zero est un geste de
# verification qui s'ecrit en toutes lettres (voir la page Migrations du site
# de documentation).
downgrade: ## Annule la derniere migration appliquee
	uv run alembic downgrade -1

history: ## Historique des migrations et revision courante
	uv run alembic history
	uv run alembic current

# Le pendant « migrations » du check de la CI, destine a QA-01. Exige une base
# demarree ET a head.
migrate-check: ## Echoue si modeles et migrations divergent
	uv run alembic check

# Contrat OpenAPI (SHARED-03). NI SERVEUR NI BASE DE DONNEES : le script importe
# `app.main` et appelle `create_app().openapi()`. Le raisonnement complet est en
# tete du script.
#
# `--locked`, alors que tout le reste de ce fichier ecrit `uv run` nu, et la
# nuance compte : c'est la SEULE cible dont la sortie est COMMITEE. Un poste dont
# le .venv aurait derive du lock -- un `uv sync -U` d'essai, une montee de
# fastapi non commitee -- produirait un schema different de celui de la CI, donc
# un diff qui ne vient d'aucun changement de contrat. `--locked` fait echouer ce
# poste-la au lieu de le laisser produire.
openapi: ## Exporte le schema OpenAPI vers packages/api-client/openapi.json
	uv run --locked python scripts/export_openapi.py

# Memes verifications, et dans le meme ordre, que le futur pipeline QA-01 : un
# echec local reproduit ainsi exactement un echec de CI. La difference est que
# `make` s'arrete au premier echec, la ou QA-01 agregera les trois.
#
# Les contrats d'architecture entrent ici par `lint`, qui les enchaine. En CI
# ils tournent des aujourd'hui, dans .github/workflows/ci-backend.yml.
check: lint format-check typecheck ## Enchaine les verifications de la CI
