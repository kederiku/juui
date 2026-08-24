# Commandes de qualite du service d'API (BACK-02).
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

.PHONY: help lint lint-fix imports format format-check typecheck check

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
	uv run mypy src

# Memes verifications, et dans le meme ordre, que le futur pipeline QA-01 : un
# echec local reproduit ainsi exactement un echec de CI. La difference est que
# `make` s'arrete au premier echec, la ou QA-01 agregera les trois.
#
# Les contrats d'architecture entrent ici par `lint`, qui les enchaine. En CI
# ils tournent des aujourd'hui, dans .github/workflows/ci-backend.yml.
check: lint format-check typecheck ## Enchaine les verifications de la CI
