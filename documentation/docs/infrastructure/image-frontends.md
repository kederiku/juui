---
title: L'image des trois frontends
description: "L'image Docker unique des frontends : les trois valeurs figées au build, la sortie standalone, le poids et la vérification à la main."
---

# L'image des trois frontends

Les trois applications Next.js de Juui — professionnelle, individuelle et admin — sortent d'une
seule et même image Docker. Cette page en décrit le Dockerfile paramétré, les valeurs figées au
moment du build, l'anatomie de la sortie standalone et la vérification de chaque image à la main.

Les trois applications Next.js se construisent depuis **un seul** Dockerfile,
`docker/frontend/Dockerfile`, paramétré par un
`ARG APP_NAME`. Rien ne les distingue à la construction — mêmes scripts, même
`next.config.ts` à leurs commentaires près : trois fichiers auraient triplé
chaque correction à venir.

| Cible    | Ce qu'elle fait                                                                           | Qui l'utilise                              |
| -------- | ----------------------------------------------------------------------------------------- | ------------------------------------------ |
| `runner` | Sortie `standalone` servie par `node server.js`, sans pnpm ni `node_modules` complet      | les trois services `frontend-*` du compose |
| `dev`    | `next dev` sur le port 3000, pnpm et les `node_modules` du monorepo, code monté en volume | `docker-compose.override.yml`              |

Un `docker build` sans `--target` construit `runner` : c'est le dernier étage du
fichier, et sa position est délibérée.

**Le contexte de build est la racine du dépôt** — ni `docker/`, ni
`frontend/<app>/`. Un build pnpm en monorepo a besoin du `pnpm-lock.yaml`, du
`pnpm-workspace.yaml`, du `package.json` racine et de tout `packages/` : aucun
sous-dossier ne les contient tous. C'est ce qui a rendu nécessaire le
`.dockerignore` de la racine, créé par ce ticket — Docker ne lit
que celui de la racine du contexte, et sans lui les 618 Mo de `node_modules`
partiraient au démon à chaque build.

```bash
docker build --build-arg APP_NAME=frontend-professional -t juui-frontend-professional:local -f docker/frontend/Dockerfile .
```

## Les trois valeurs figées au build

Ce sont celles que `.env.example` annonce déjà comme passées « en
`build.args` », et que les trois services `frontend-*` du compose leur passent
effectivement depuis INFRA-05b :

| Argument              | Applications          | Ce qu'il devient                                                    |
| --------------------- | --------------------- | ------------------------------------------------------------------- |
| `NEXT_PUBLIC_API_URL` | les trois             | remplacé littéralement dans le bundle envoyé au navigateur          |
| `API_INTERNAL_URL`    | les trois             | lu par le serveur Next — `http://api:8000` en conteneur             |
| `SITE_URL`            | `frontend-individual` | `metadataBase`, `robots.txt` et `sitemap.xml`, tous trois prérendus |

:::warning Valeurs figées au build
Ces valeurs sont **figées au moment du build**, pas lues au
démarrage. Les changer impose de **reconstruire** l'image : un
`docker compose restart` ne changera rien.
:::

Un argument non passé reste **absent** de l'environnement du build — et non vide.
La nuance compte : le repli que chaque application prévoit s'applique alors
normalement, là où une chaîne vide le contournerait. Construite sans `SITE_URL`,
`frontend-individual` publie donc un sitemap en `http://localhost:3002` au lieu
d'échouer sur un `Invalid URL`.

## L'anatomie de la sortie standalone

`next build` ne recopie dans `.next/standalone` que les modules que son traçage a
vu importer — c'est tout l'intérêt de l'image. Deux choses lui échappent
toujours, `.next/static` et `public/`, qu'il suppose servis par un CDN : l'étage
`builder` les remet en place, faute de quoi la page s'afficherait **sans aucune
feuille de style**, et sans la moindre erreur.

L'arborescence obtenue est celle du dépôt vue depuis `outputFileTracingRoot`,
que les trois `next.config.ts` fixent à la racine (FRONT-01) :

```
/app
├── node_modules/                        les modules tracés, 38 Mo
└── frontend/frontend-professional/
    ├── server.js                        le serveur minimal, lancé par le CMD
    ├── .next/                           pages compilées, plus static/ et cache/
    └── package.json
```

Elle est recopiée **telle quelle** : les `node_modules` qu'elle contient sont un
arbre de liens symboliques pnpm, que déplacer ou aplatir casserait. C'est aussi
pourquoi l'image fixe son `WORKDIR` sur le dossier de l'application plutôt que
d'interpoler `APP_NAME` dans son `CMD` — une forme `exec` de `CMD` n'interpole
aucune variable, un `WORKDIR`, si.

## Ce que pèsent les images

| Mesure                                        | frontend (chacune des trois) |
| --------------------------------------------- | ---------------------------- |
| Blobs compressés (`docker image inspect`)     | 95 Mo                        |
| Couches décompressées (`docker history`)      | ≈ 309 Mo                     |
| Occupation réelle dans le conteneur (`du -s`) | 292 Mo                       |
| dont image `node:24.19.0-trixie-slim` nue     | 253 Mo                       |
| dont l'application et ses modules tracés      | 39 Mo                        |

`docker image ls` en annonce 405 Mo, et c'est la même mise en garde qu'à la
section précédente : ce chiffre est le `DISK USAGE` du magasin containerd, qui
compte les blobs compressés **et** leur copie décompressée. Les 39 Mo de la
dernière ligne sont la mesure qui décrit le travail de ce ticket — à comparer aux
618 Mo du `node_modules` du monorepo, que l'image ne contient pas.

```bash
docker run --rm juui-frontend-professional:local sh -c 'du -sh /app /app/node_modules'
```

## Vérifier une image à la main

```bash
docker run --rm -p 3001:3000 juui-frontend-professional:local
```

L'accueil répond alors **200** sur [http://localhost:3001](http://localhost:3001), servi par l'utilisateur
non-root `juui` (uid 1001, le même que l'image d'API). Même chose pour
`frontend-individual` sur 3002.

`frontend-admin`, lui, répond **307 vers `/login`** : son accueil vit dans le
groupe `(protected)` et `proxy.ts` redirige toute requête sans session
(FRONT-03). C'est `/login` qui rend 200 — la redirection est le comportement
attendu, pas une panne.

Les écarts assumés avec le ticket INFRA-05a sont consignés au
[registre des écarts](../ecarts/infra.md#écarts-assumés-avec-le-ticket-infra-05a).
