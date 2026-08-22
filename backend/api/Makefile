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

.PHONY: help lint lint-fix format format-check typecheck check

help: ## Affiche cette aide
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-13s\033[0m %s\n", $$1, $$2}'

lint: ## Signale les infractions au jeu de regles Ruff
	uv run ruff check .

lint-fix: ## Corrige ce que Ruff sait corriger sans risque
	uv run ruff check --fix .

format: ## Reformate le code (et les blocs Python de la documentation)
	uv run ruff format .

format-check: ## Verifie le formatage sans rien reecrire
	uv run ruff format --check .

typecheck: ## Verifie le typage en mode strict
	uv run mypy src

# Memes verifications, et dans le meme ordre, que le futur pipeline QA-01 : un
# echec local reproduit ainsi exactement un echec de CI. La difference est que
# `make` s'arrete au premier echec, la ou QA-01 agregera les trois.
check: lint format-check typecheck ## Enchaine les trois verifications de la CI
