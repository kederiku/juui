---
title: Le mode développement
description: 'La variante compose à deux fichiers : ce que chaque service y gagne, ce que les montages recouvrent et le rechargement à chaud.'
---

# Le mode développement

Démarrée telle quelle, la pile Docker sert des images figées — chaque modification du poste
exigerait une reconstruction. Cette page décrit la variante à deux fichiers compose qui monte
le code du poste dans les conteneurs et rend le rechargement à chaud aux services du dépôt.

Les commandes de la page [Démarrer la pile](../getting-started/demarrage.md)
démarrent la pile sur les images **servies** :
l'API sans rechargement, les trois frontends sur leur sortie `standalone`. Rien
de ce qu'on modifie sur le poste n'y change quoi que ce soit — il faut
reconstruire. Pour travailler, `docker/docker-compose.override.yml`
bascule les cinq services que le dépôt construit lui-même sur leur cible `dev`
et leur monte le code du poste.

:::warning L'override n'est jamais chargé tout seul

Compose charge d'office un `docker-compose.override.yml` **uniquement**
lorsqu'il a découvert le fichier de base lui-même. Dès qu'un `-f` est passé —
ce que fait toute commande du dépôt, sans quoi le `.env` de la racine ne
serait pas lu — l'override est **silencieusement ignoré**. Il faut donc le
nommer, et c'est le seul moyen.

:::

```bash
docker compose --project-directory . -f docker/docker-compose.yml -f docker/docker-compose.override.yml up -d --build
```

Sans ce second `-f`, la pile repart sur les images servies : aucun montage,
aucun rechargement à chaud, et pas la moindre erreur pour le dire. `make up` et
`make dev` encapsulent les deux invocations.

Les ports, les URLs et les identifiants ne changent pas d'un mode à l'autre :
ceux de la page [Ports et URLs des services](./ports-et-services.md) valent dans les deux.

## Ce que chaque service y gagne

| Service      | Cible de base | Cible en développement | Ce qui est monté   |
| ------------ | ------------- | ---------------------- | ------------------ |
| `api`        | `prod`        | `dev`                  | `./backend/api`    |
| `worker`     | `worker`      | `dev`                  | `./backend/api`    |
| `frontend-*` | `runner`      | `dev`                  | la racine du dépôt |

Les six briques d'infrastructure — `postgres`, `pgadmin`, `redis`,
`redisinsight`, `minio`, `minio-init` et `mailpit` — n'apparaissent pas dans
l'override : elles tirent des images publiques et se comportent de la même façon
dans les deux modes.

Le `worker` est le seul à devoir **redire sa commande**. Sa cible de base
installe le paquet en `--no-editable` : ses imports passent par `/opt/venv`, et
lui monter du code n'y changerait rien. Seule la cible `dev` est éditable — mais
son `CMD` est `uvicorn`. La commande `taskiq worker` est donc réécrite dans
l'override, seconde source de vérité à côté du `CMD` de la cible `worker`, à
tenir alignée.

## Ce que les montages recouvrent — et ce qu'ils masquent

Les trois frontends montent **la racine du dépôt** sur `/app`, et non le seul
dossier de leur application : c'est ce qui fait traverser le Fast Refresh la
frontière du monorepo, une modification de `packages/ui` ou du thème de
`packages/config-tailwind` se voyant au même titre qu'une modification de page.

Trois volumes anonymes masquent alors ce qui ne doit surtout pas venir de
l'hôte. Un volume anonyme posé sur un chemin que le montage recouvre le **rend à
l'image** : le conteneur retrouve son propre contenu.

| Chemin masqué                      | Pourquoi                                                                       |
| ---------------------------------- | ------------------------------------------------------------------------------ |
| `/app/node_modules`                | ceux du poste sont construits pour macOS — l'image a les siens, pour Linux     |
| `/app/frontend/<app>/node_modules` | second niveau de l'arbre pnpm ; n'en masquer qu'un laisse l'autre dans le vide |
| `/app/frontend/<app>/.next`        | le cache Turbopack du poste porte des chemins absolus de l'hôte                |

Les `node_modules` des **autres** workspaces — `packages/*`, `documentation/` —
ne sont pas masqués, et n'ont pas à l'être : les liens symboliques que pnpm y
dépose sont **relatifs** et pointent tous vers `../../node_modules/.pnpm/…`,
donc, dans le conteneur, vers le volume anonyme du premier niveau. Vérifié :

```bash
docker compose --project-directory . -f docker/docker-compose.yml -f docker/docker-compose.override.yml exec frontend-professional sh -c 'ls /app/node_modules/.pnpm | grep swc; readlink -f /app/frontend/frontend-professional/node_modules/next'
```

La commande affiche `@next+swc-linux-arm64-gnu@16.3.2` — et non la variante
`darwin` qu'a le poste — puis un chemin qui plonge dans `/app/node_modules`.

:::note L'API relit son dotenv

L'installation éditable fait résoudre `config.py` en
`/app/src/app/core/config.py`, donc son `_ENV_FILE` en `/app/.env` — fichier
absent de l'image, mais ramené par le montage. Sans conséquence,
pydantic-settings donnant la priorité aux variables du **processus** sur le
dotenv : ce que compose passe l'emporte. Mais une variable oubliée côté
compose s'y replierait **en silence**, avec la valeur d'un fichier écrit pour
un `uvicorn` lancé hors Docker — où `POSTGRES_HOST` vaut `localhost`.

:::

## Constater le rechargement à chaud

Côté frontend, modifier un fichier de `frontend/frontend-professional/app/` et
recharger [http://localhost:3001](http://localhost:3001) : la page change, et `docker compose logs`
montre une recompilation Turbopack — aucun `docker build` n'est relancé.

Côté API, modifier un fichier de `backend/api/src/` :

```bash
docker compose --project-directory . -f docker/docker-compose.yml -f docker/docker-compose.override.yml logs api --tail 5
```

`WARNING:  WatchFiles detected changes in 'src/app/main.py'. Reloading...` suivi
d'un `Application startup complete.` Le `--reload-dir /app/src` du `CMD` limite
la surveillance aux sources : sans lui, un passage de Ruff sur le poste
redémarrerait le serveur.

Les écarts assumés avec le ticket INFRA-05b sont consignés au
[registre des écarts](../ecarts/infra.md#écarts-assumés-avec-le-ticket-infra-05b).
