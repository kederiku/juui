---
title: Conventions du dépôt
description: Style de code, langue du code, hooks de pre-commit et convention de commit — ce que le dépôt vérifie avant chaque commit.
---

# Conventions du dépôt

Le dépôt ne repose pas sur la mémoire de chacun — style de code, langue du code,
hooks de pre-commit et convention de commit sont outillés, et cette page décrit
ce que ces garde-fous vérifient avant chaque commit.

:::note Repris par DOC-02c

Le guide de contribution (`CONTRIBUTING.md`, DOC-02c) reprendra ce contenu.

:::

- Fins de ligne LF, UTF-8, indentation à 2 espaces (4 pour Python) : voir
  `.editorconfig`.
- `main` est la branche de référence ; toute modification passe par une branche
  dédiée puis une pull request.

## Style de code

Point-virgule final, guillemets simples, virgule finale partout, largeur de ligne
à 100 caractères. La configuration fait foi — personne n'a à retenir cette liste :

```bash
pnpm format && pnpm lint
```

Plus besoin d'y penser avant un commit : le [hook de
pre-commit](#hooks-de-pre-commit) applique ces deux passes aux fichiers indexés.
Ces commandes restent utiles pour reformater le dépôt d'un coup, après un
changement de configuration par exemple.

Prettier ne remet jamais la prose à la ligne (`proseWrap: 'preserve'`) : les
paragraphes du Markdown restent découpés à la main. Il réaligne en revanche les
tableaux, ce qui allonge leurs lignes source.

## Langue du code

Les **identifiants sont en anglais** — classes, fonctions, variables, arguments,
noms de fichiers — et les **commentaires et docstrings en français**. Un port
s'appelle `AccountRepository`, une fonction de mapping `_to_entity` ; ce qui les
entoure explique en français pourquoi ils existent. Le code se lit comme celui de
ses dépendances, l'intention se lit dans la langue de l'équipe.

Les **accents s'arrêtent au Markdown**. Commentaires et docstrings Python,
commentaires YAML et shell, messages `echo` et messages de commit s'écrivent sans
accents ; seuls les fichiers `.md` sont pleinement accentués. Les tirets longs
s'écrivent `--` dans le code et `—` en Markdown.

## Hooks de pre-commit

`pnpm install` installe les hooks Git en même temps que les dépendances : le
script `prepare` lance [Husky](https://typicode.github.io/husky/), qui fait
pointer `core.hooksPath` sur `.husky/_`. Rien d'autre à faire, rien à relancer.

| Hook                | Ce qu'il lance      | Ce qu'il vérifie                     |
| ------------------- | ------------------- | ------------------------------------ |
| `.husky/pre-commit` | `lint-staged`       | Le contenu des fichiers **indexés**. |
| `.husky/commit-msg` | `commitlint --edit` | Le message du commit.                |

`lint-staged` ne traite **que les fichiers indexés**, jamais le dépôt entier —
c'est ce qui garde le hook sous les dix secondes :

| Fichiers indexés            | Traitement                                          |
| --------------------------- | --------------------------------------------------- |
| `*.{ts,tsx,js,jsx,mjs,cjs}` | `eslint --fix` puis `prettier --write`              |
| `*.{json,md,yaml,yml}`      | `prettier --write`                                  |
| `backend/**/*.py`           | `ruff check --fix` puis `ruff format`, via `uv run` |

Ce qui est corrigeable est **corrigé puis ré-indexé** : le commit part propre
sans rien vous demander. Ce qui ne l'est pas — erreur ESLint sans correction
automatique, règle Ruff non corrigeable, annotation de type manquante —
**interrompt le commit**. Le détail, chaque choix accompagné de sa raison, est
dans `lint-staged.config.mjs`.

:::note Prérequis du volet Python

**Le volet Python exige `uv` sur le poste.** Qui ne touche jamais au backend
n'a rien à installer : cette entrée ne se déclenche que sur un `.py` indexé.

:::

Le budget de dix secondes tient malgré le passage du lint en mode _type-aware_
(SETUP-06) : un fichier `.ts` indexé fait désormais construire un programme
TypeScript, ce qui porte sa passe ESLint de 0,5 s à 1,3 s, et un commit touchant
trois workspaces à la fois de 0,6 s à 2,2 s. Un fichier `.mjs`, hors typage, ne
bouge pas. C'est le seul endroit du dépôt où ces règles tournent avant une pull
request : la CI existe, mais elle ne rejoue à ce jour que les
[contrats d'architecture](../backend/qualite-et-typage.md#import-linter), les
[frontières entre features](../frontend/structure-par-domaine.md), la
régénération du client d'API et le build du site. Ruff, Mypy et pytest y entreront
avec QA-01 et QA-02. Dispenser les hooks de ces règles les rendrait donc
facultatives, pour de bon.

Trois situations, trois gestes :

| Situation                                        | Geste                                               |
| ------------------------------------------------ | --------------------------------------------------- |
| **Urgence** : livrer sans passer par les hooks   | `git commit --no-verify`                            |
| Environnement sans hooks (image Docker, CI)      | `HUSKY=0 pnpm install`                              |
| Les hooks ne se déclenchent plus                 | `pnpm prepare`                                      |
| Client Git graphique : `node: command not found` | Exporter le `PATH` depuis `~/.config/husky/init.sh` |

Le troisième cas se produit après un `HUSKY=0 pnpm install` : un `pnpm install`
ultérieur ne réinstalle rien s'il n'a rien à installer, et ne relance donc pas
`prepare`. `pnpm prepare` repose les hooks en une seconde.

**`--no-verify` est réservé aux urgences** — un correctif de production à 3 h du
matin, pas un lint qui agace.

:::danger Ce que `--no-verify` laisse passer n'est rattrapé par personne
Tant que QA-01 et QA-02 ne sont pas livrés, la CI backend ne rejoue que les contrats
d'architecture. Une erreur Ruff ou Mypy contournée au commit **arrive telle quelle
sur `main`**. Après un `--no-verify`, lancer `make lint` et `make typecheck` à la
main est le minimum.
:::

Le dernier cas vient de ce qu'un client graphique n'hérite pas du `PATH` d'un
terminal de connexion : il ne trouve donc pas Node, dont dépendent `lint-staged`
et `commitlint`. Husky lit `~/.config/husky/init.sh` avant chaque hook, c'est là
que ça se répare :

```sh
# ~/.config/husky/init.sh
export PATH="/opt/homebrew/bin:$PATH"
```

(Les binaires du dépôt, eux, sont déjà trouvés : husky place `node_modules/.bin`
en tête du `PATH` de ses hooks.)

## Convention de commit

Les messages suivent [Conventional Commits](https://www.conventionalcommits.org/fr/),
vérifiés par commitlint :

```
type(scope facultatif): sujet
```

Huit types, et un sujet en français à l'infinitif, sans majuscule initiale ni
point final :

| Type       | Quand l'employer                                      |
| ---------- | ----------------------------------------------------- |
| `feat`     | Nouvelle fonctionnalité.                              |
| `fix`      | Correction d'un défaut.                               |
| `chore`    | Outillage, dépendances, tâche sans effet fonctionnel. |
| `docs`     | Documentation seule.                                  |
| `refactor` | Réécriture à comportement constant.                   |
| `test`     | Ajout ou modification de tests.                       |
| `ci`       | Intégration continue.                                 |
| `build`    | Build, conteneurs, publication.                       |

Le scope est **facultatif** ; s'il est présent, il désigne un workspace : `api`,
`professional`, `individual`, `admin`, `ui`, `api-client`, `config-typescript`,
`config-tailwind`, `config-eslint`, `config-prettier`, `docker`,
`documentation`. La liste
suit l'arborescence réelle — **un nouveau workspace ajoute son scope à
`commitlint.config.mjs` dans la pull request qui le
crée**.

```
chore: configurer les workspaces pnpm (SETUP-02)
feat(api): exposer la sonde de santé
```

Les commits de merge, de revert, de fixup et de squash sont ignorés d'office :
un `git merge` local ne sera pas rejeté.

Les écarts assumés avec les tickets SETUP-04, SETUP-06 et SETUP-07 sont consignés au
[registre des écarts](../ecarts/setup.md).
