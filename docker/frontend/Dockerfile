# syntax=docker/dockerfile:1

# Image des trois applications Next.js (INFRA-05a, consommee par INFRA-05b et QA-03).
#
# UN SEUL FICHIER POUR TROIS APPLICATIONS. Ce que le ticket demande, et ce que
# le depot rend possible : les trois `next.config.ts` sont identiques a leurs
# commentaires pres (FRONT-01 en est le patron), leurs `package.json` declarent
# les memes scripts, et seul le nom du workspace les distingue. Un `ARG APP_NAME`
# suffit donc, la ou trois fichiers auraient triple chaque correction a venir.
#
#   docker build --build-arg APP_NAME=frontend-professional \
#     -f docker/frontend/Dockerfile -t juui-frontend-professional:local .
#
# LE CONTEXTE DE BUILD EST LA RACINE DU DEPOT, ET IL NE PEUT PAS EN ETRE
# AUTREMENT. Un build Next.js en monorepo pnpm a besoin du pnpm-lock.yaml, du
# pnpm-workspace.yaml, du package.json racine, des trois frontend/* et de tout
# packages/* : aucun sous-dossier ne les contient tous. D'ou le `.dockerignore`
# de la RACINE, cree par ce ticket -- Docker ne lit qu'un seul fichier
# d'exclusion, `<contexte>/.dockerignore`.
#
# C'est la difference majeure avec docker/api/Dockerfile (INFRA-04), dont le
# contexte est backend/api et qui doit passer son entrypoint par un contexte
# ADDITIONNEL. Ici tout est dans le contexte : ni `--build-context`, ni
# `additional_contexts` cote compose.
#
# SIX ETAGES, DEUX CIBLES UTILES : `dev` et `runner`. Les quatre autres --
# `base`, `toolchain`, `deps`, `builder` -- ne sont que des paliers partages.
#
# CE QUE CE FICHIER NE FAIT PAS
# Aucun HEALTHCHECK : le depot declare toutes ses sondes dans le fichier compose,
# depuis INFRA-01. Celles des trois frontends reviennent a INFRA-05b.
# Aucun entrypoint non plus : contrairement a l'API, un frontend n'a ni base a
# attendre ni migration a appliquer. Le serveur demarre, c'est tout.

# Version de Node, EPINGLEE au correctif. C'est celle du poste, celle qu'annonce
# .nvmrc (« 24 ») et celle que couvre le `engines.node` du package.json racine
# (« >=24.14 »). Une image de build qui suivrait la derniere 24.x changerait de
# compilateur sans qu'aucune ligne du depot n'ait bouge.
ARG NODE_VERSION=24.19.0

# Distribution Debian NOMMEE plutot que le `-slim` nu, exactement comme
# INFRA-04 : sans elle, une bascule de Debian en amont changerait la libc et les
# paquets systeme d'un `docker build` a l'autre.
ARG DEBIAN_RELEASE=trixie

# A TENIR ALIGNE AVEC LE CHAMP `packageManager` DU package.json RACINE. L'etage
# `deps` verifie cet alignement et fait echouer le build s'il est rompu -- voir
# plus bas. Debian ne fournit pas pnpm et l'image officielle de Node n'embarque
# PAS corepack (verifie dans le Dockerfile amont de nodejs/docker-node) : il faut
# donc l'installer, et donc en nommer la version ici.
ARG PNPM_VERSION=11.22.0


# =============================================================================
# base -- socle commun a tous les etages
# =============================================================================
FROM node:${NODE_VERSION}-${DEBIAN_RELEASE}-slim AS base

# Telemetrie de Next.js coupee : elle sortirait du reseau a chaque `next build`,
# depuis la CI comme depuis un poste. Le .env.local.example de chaque application
# offre deja ce reglage au developpeur ; ici il n'est pas negociable.
ENV NEXT_TELEMETRY_DISABLED=1 \
    \
    # Le `prepare: husky` du package.json racine s'execute a CHAQUE
    # `pnpm install`, y compris celui de l'etage `deps`. Verifie : husky 9.1.7
    # se contente d'ecrire « .git can't be found » et sort en 0, donc rien ne
    # casse -- mais la variable dit l'intention, et elle couvre le jour ou .git
    # entrerait dans le contexte de build.
    HUSKY=0

WORKDIR /app

# Utilisateur non-root, cree ici pour que TOUS les etages partagent le meme
# uid/gid. L'uid 1001 n'est pas choisi au hasard : c'est celui de l'image d'API
# (INFRA-04). Une pile ou chaque service ecrit sous un uid different rendrait
# imprevisibles les droits sur les volumes montes -- ce que fait precisement
# INFRA-05b en montant le code du poste dans la cible `dev`.
#
# L'image officielle de Node embarque deja un compte `node` en uid 1000. On ne
# s'en sert pas : deux uid dans la pile pour deux images maison serait une
# divergence sans contrepartie.
RUN groupadd --system --gid 1001 juui \
    && useradd --system --uid 1001 --gid juui --no-create-home --shell /usr/sbin/nologin juui


# =============================================================================
# toolchain -- socle des etages qui ont besoin de pnpm
# =============================================================================
FROM base AS toolchain

ARG PNPM_VERSION

# LE STORE PNPM VIT HORS DE /app, ET C'EST LE MEME RAISONNEMENT QUE LE /opt/venv
# D'INFRA-04. La cible `dev` tourne avec le code MONTE EN VOLUME sur /app
# (INFRA-05b) : tout ce que le montage recouvre disparait aux yeux du conteneur.
ENV PNPM_HOME=/pnpm \
    PATH=/pnpm:$PATH

# `npm install -g` plutot que corepack : l'image officielle de Node ne l'embarque
# pas. La version est celle de l'ARG ci-dessus, elle-meme alignee sur le champ
# `packageManager` -- alignement verifie a l'etage suivant.
RUN npm install --global pnpm@${PNPM_VERSION}


# =============================================================================
# deps -- dependances du monorepo entier
# =============================================================================
FROM toolchain AS deps

ARG PNPM_VERSION

# COUCHE 1 -- LE TELECHARGEMENT SEUL.
#
# `pnpm fetch` ne lit QUE le fichier de verrouillage : il ignore les manifestes
# et remplit le store. C'est ce qui satisfait le critere « un changement de code
# seul ne retelecharge pas les dependances » -- l'empreinte de cette couche ne
# depend que de ces deux fichiers, et le lockfile ne bouge qu'a l'ajout d'une
# dependance.
#
# pnpm-workspace.yaml accompagne le lockfile parce que, depuis pnpm 11, c'est LUI
# qui porte les reglages d'installation du depot (strictPeerDependencies,
# autoInstallPeers, allowBuilds) -- .npmrc n'est plus lu que pour `registry` et
# `auth`.
COPY pnpm-lock.yaml pnpm-workspace.yaml ./

RUN pnpm fetch

# COUCHE 2 -- LE CODE, PUIS L'INSTALLATION.
# Ce que le contexte contient encore apres le .dockerignore de la racine : les
# trois frontend/*, packages/*, documentation/, les manifestes et les fichiers de
# configuration de la racine.
COPY . .

# GARDE D'ALIGNEMENT. pnpm est installe depuis un ARG, mais le depot declare sa
# version dans `packageManager` : deux sources de verite, donc une occasion de
# diverger. Le build echoue ici, avec un message qui nomme les deux valeurs,
# plutot que de fabriquer en silence une image construite par une autre version
# de pnpm que celle du poste et de la CI.
RUN declared="$(node -p "require('./package.json').packageManager")"; \
    if [ "$declared" != "pnpm@${PNPM_VERSION}" ]; then \
      echo "INFRA-05a : PNPM_VERSION=${PNPM_VERSION} desaligne de packageManager=$declared" >&2; \
      echo "INFRA-05a : aligner l'ARG PNPM_VERSION de ce Dockerfile sur le package.json racine." >&2; \
      exit 1; \
    fi

# `--frozen-lockfile` interdit toute re-resolution : si pnpm-lock.yaml ne
# correspond plus aux manifestes, le build ECHOUE au lieu de produire une image
# qui ne contient pas les versions verrouillees.
#
# `--offline` n'est pas decoratif : il INTERDIT le reseau. C'est ce qui prouve
# que la couche `pnpm fetch` ci-dessus a bien fait son travail. Sans lui, un
# paquet absent du store serait rattrape en silence par le registre, et le
# decoupage en deux couches ne garantirait plus rien.
RUN pnpm install --frozen-lockfile --offline


# =============================================================================
# builder -- construction d'UNE application
# =============================================================================
FROM deps AS builder

ARG APP_NAME

# Les trois variables que .env.example et les trois .env.local.example annoncent
# deja comme passees « en build.args par docker compose ». Elles sont des ARG et
# non des variables d'execution parce que Next les FIGE AU BUILD : NEXT_PUBLIC_*
# est litteralement remplacee dans le bundle client, et SITE_URL est lue par des
# pages, un robots.txt et un sitemap.xml prerendus. Les changer impose de
# RECONSTRUIRE l'image ; un `docker compose restart` ne changera rien.
#
# Aucune valeur par defaut ici : ce sont celles du .env de la racine, dont
# .env.example porte les exemples. Une valeur de repli ecrite dans ce fichier
# serait une seconde source de verite, et c'est exactement ce qu'INFRA-04 s'est
# refuse a faire.
#
# ET AUCUN `ENV` NON PLUS, CE QUI EST CONTRE-INTUITIF. Un ARG est deja visible
# dans l'environnement du `RUN` ci-dessous : le recopier en ENV n'ajouterait
# rien, et casserait quelque chose. Verifie : un ARG NON PASSE est ABSENT de
# l'environnement, la ou `ENV SITE_URL=${SITE_URL}` en ferait une chaine VIDE.
# La difference n'est pas theorique -- `app/site-url.ts` (FRONT-02) se replie sur
# `http://localhost:3002` avec `??`, qui ne rattrape pas la chaine vide : le
# build echouerait sur un « Invalid URL » dans `new URL(SITE_URL)` au lieu de se
# replier comme l'application le prevoit.
ARG NEXT_PUBLIC_API_URL
ARG API_INTERNAL_URL
ARG SITE_URL

# Sans APP_NAME, `pnpm --filter ""` ne s'arrete pas : il balaie le depot et
# construit ce qu'il trouve. Le build echouerait plus loin, sur un `COPY` de
# chemin introuvable, avec un message qui ne nomme pas la cause.
RUN test -n "${APP_NAME}" \
    || (echo "INFRA-05a : --build-arg APP_NAME=<frontend-professional|frontend-individual|frontend-admin> est obligatoire" >&2; exit 1)

# `--filter` sans `...` : aucun package partage n'a de script `build`. SHARED-01
# publie `@repo/ui` en SOURCE TypeScript, transpilee par Next via le
# `transpilePackages` des applications -- il n'y a rien a construire en amont.
#
# LES DEUX `cp` NE SONT PAS UN DETAIL. Next ne recopie JAMAIS `.next/static` ni
# `public/` dans sa sortie standalone : il les suppose servis par un CDN. Sans
# eux l'image se construit, le serveur demarre, et la page s'affiche SANS aucune
# feuille de style ni script -- une panne qui ne produit aucune erreur.
#
# Les chemins passent par `frontend/${APP_NAME}/` DANS la sortie standalone :
# celle-ci reproduit l'arborescence a partir de `outputFileTracingRoot`, que les
# trois next.config.ts fixent a la racine du depot (FRONT-01).
#
# `public/` est sous garde de presence : aucune des trois applications n'en a un
# aujourd'hui, et un `cp` de chemin absent ferait echouer le build. L'etape
# s'activera d'elle-meme le jour ou l'une d'elles en aura un, sans qu'on ait a
# revenir sur ce fichier.
RUN pnpm --filter "${APP_NAME}" build \
    && cp -r "frontend/${APP_NAME}/.next/static" \
             "frontend/${APP_NAME}/.next/standalone/frontend/${APP_NAME}/.next/static" \
    && if [ -d "frontend/${APP_NAME}/public" ]; then \
         cp -r "frontend/${APP_NAME}/public" \
               "frontend/${APP_NAME}/.next/standalone/frontend/${APP_NAME}/public"; \
       fi


# =============================================================================
# dev -- rechargement a chaud, code monte en volume
# =============================================================================
# Ne descend PAS de `builder` : cette cible ne construit rien, elle a besoin des
# node_modules complets et de pnpm, que l'image servie n'embarque pas.
#
# A SAVOIR POUR INFRA-05b : le montage du code sur /app doit EXCLURE les
# node_modules, et il y en a DEUX niveaux -- /app/node_modules et
# /app/frontend/<app>/node_modules. L'arbre pnpm est fait de liens symboliques du
# second vers le premier ; n'en masquer qu'un rend l'autre pendant dans le vide.
FROM deps AS dev

ARG APP_NAME

RUN test -n "${APP_NAME}" \
    || (echo "INFRA-05a : --build-arg APP_NAME=<...> est obligatoire" >&2; exit 1)

# LE SEUL `chown` DU FICHIER, et il ne porte QUE sur le dossier de
# l'application. Contrairement a l'API, un serveur de developpement Next ECRIT
# dans le code qu'il sert : `.next/` d'abord, mais aussi `next-env.d.ts`, qu'il
# regenere a chaque demarrage. Les deux ont ete constates ici, l'un apres
# l'autre, sous forme de « EACCES: permission denied » qui laissent le conteneur
# vivant mais muet -- seuls les journaux les nomment.
#
# `-R` sur ce dossier seulement, JAMAIS sur /app : le monorepo entier ferait une
# couche de plusieurs centaines de mega-octets pour rien. Ce qui est ici tient en
# quelques fichiers et en des liens symboliques, dont `chown -R` ne suit pas les
# cibles.
#
# A SAVOIR POUR INFRA-05b : une fois le code du poste monte sur ce dossier, c'est
# l'HOTE qui en fixe le proprietaire et ce chown ne vaut plus. Sous Docker
# Desktop le montage se presente sous l'uid qui l'ouvre, donc rien a faire ; sous
# Linux, un uid d'hote different de 1001 redonnera les memes EACCES.
#
# LE `mkdir` A ETE AJOUTE PAR INFRA-05b, ET IL N'EST PAS DECORATIF. Son fichier
# d'override masque `.next` par un volume anonyme, pour que le cache Turbopack du
# poste -- chemins absolus de l'hote, artefacts SWC darwin -- n'entre pas dans le
# conteneur. Or Docker n'initialise un volume qu'a partir de ce que l'IMAGE porte
# au point de montage : si le dossier n'y existe pas, il le cree lui-meme, en
# root, et le serveur non-root ne peut plus rien y ecrire. Constate exactement
# ainsi -- « EACCES: permission denied, mkdir .next/dev », en boucle de
# redemarrage. Creer le dossier ici, avant le chown, donne au volume le
# proprietaire qu'il faut.
RUN mkdir -p "/app/frontend/${APP_NAME}/.next" \
    && chown -R juui:juui "/app/frontend/${APP_NAME}"

# Le repertoire de travail EST la parametrisation : une forme `exec` de CMD
# n'interpole aucune variable, mais WORKDIR, si. C'est ce qui evite d'envelopper
# la commande dans un `sh -c` -- meme arbitrage qu'INFRA-04.
WORKDIR /app/frontend/${APP_NAME}

USER juui

EXPOSE 3000

# `next dev` DIRECTEMENT, et non `pnpm dev`. Le script `dev` du package.json fixe
# le port du POSTE (3001, 3002 ou 3003) ; en conteneur les trois applications
# ecoutent sur 3000, c'est la publication qui les distingue -- le tableau des
# ports du site de documentation en fait une regle, et elle doit valoir dans
# les deux modes.
#
# `--hostname 0.0.0.0` : sans lui le serveur de developpement n'ecoute que la
# boucle locale DU CONTENEUR, et le port publie ne mene nulle part.
CMD ["pnpm", "exec", "next", "dev", "--port", "3000", "--hostname", "0.0.0.0"]


# =============================================================================
# runner -- image servie, DERNIER ETAGE DU FICHIER
# =============================================================================
# Sa position n'est pas esthetique : Docker construit le DERNIER etage quand
# aucun `--target` n'est passe. Mettre `dev` ici ferait produire l'image de
# developpement a un `docker build` nu -- une erreur silencieuse et difficile a
# voir. Meme regle qu'en INFRA-04.
FROM base AS runner

ARG APP_NAME

ENV NODE_ENV=production \
    \
    # Les deux SEULES variables que lit le `server.js` de la sortie standalone.
    # Les ecrire ici les rend visibles dans `docker image inspect` et
    # surchargeables depuis le fichier compose, au lieu de dependre d'un defaut
    # amont. HOSTNAME=0.0.0.0 est ce qui rend le port publie effectif : sur la
    # boucle locale, le serveur serait injoignable depuis l'hote.
    PORT=3000 \
    HOSTNAME=0.0.0.0

# TOUTE L'IMAGE SERVIE TIENT DANS CE SEUL COPY. La sortie standalone contient le
# serveur, les pages compilees et les SEULS modules que le tracage a vu importer
# -- pas le node_modules complet du monorepo, qui pese plusieurs centaines de
# mega-octets.
#
# Son arborescence est celle du depot vue depuis `outputFileTracingRoot` : les
# modules a la racine, l'application sous frontend/<app>/. On la recopie TELLE
# QUELLE. L'aplatir ou deplacer le dossier de l'application casserait les liens
# symboliques pnpm que Next y a reproduits, et le serveur echouerait au demarrage
# sur un module introuvable.
COPY --from=builder /app/frontend/${APP_NAME}/.next/standalone ./

# LE SEUL DOSSIER QUI APPARTIENNE A `juui`, et c'est voulu. Tout le reste
# n'appartient qu'a root et reste lisible par tous : le processus execute son
# propre code sans pouvoir le reecrire (choix d'INFRA-04). L'optimiseur d'images
# de Next, lui, a besoin d'ecrire, et seulement la.
RUN mkdir -p "/app/frontend/${APP_NAME}/.next/cache" \
    && chown juui:juui "/app/frontend/${APP_NAME}/.next/cache"

WORKDIR /app/frontend/${APP_NAME}

USER juui

EXPOSE 3000

CMD ["node", "server.js"]
