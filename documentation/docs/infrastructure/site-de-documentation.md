---
title: Le site de documentation
description: 'Le site Docusaurus : le lancer en local, la recherche, et la chaîne qui le publie sur GitHub Pages.'
---

# Le site de documentation

La documentation technique de Juui — dont la page que vous lisez — est un site Docusaurus qui vit
dans le monorepo. Cette page couvre son lancement en local, la particularité de la barre de
recherche, et la chaîne qui le publie sur GitHub Pages.

La documentation technique du dépôt vit dans `documentation/` :
un site [Docusaurus](https://docusaurus.io/) en TypeScript, workspace pnpm au
même titre que les trois applications.

```bash
pnpm --filter documentation dev
```

Il écoute sur le port 3004 — [http://localhost:3004](http://localhost:3004). Il n'est pas conteneurisé :
rien d'autre à démarrer, et le `pnpm dev` de la racine le lance en même temps que
les trois interfaces.

**La barre de recherche fait exception.** Le plugin de recherche locale ne
construit son index qu'à la construction du site : sous `dev`, la barre est
absente. Pour l'essayer, il faut construire puis servir :

```bash
pnpm --filter documentation build && pnpm --filter documentation start
```

L'ordre de lecture des sections reste écrit à la main dans `sidebars.ts` plutôt que déduit de
l'arborescence des fichiers. Le registre des ADR est livré (DOC-02b) ; la section Architecture
attend DOC-02a, et le guide de contribution viendra avec DOC-02c.

Deux capacités sont acquises dès maintenant, parce qu'elles décident de la façon
d'écrire la suite :

- **Recherche locale**, sans service externe : l'index est un fichier du site,
  aucune requête ne sort du navigateur.
- **Diagrammes Mermaid** : un schéma d'architecture se versionne en texte et se
  relit en diff, là où une image binaire ne se relit pas. La page d'accueil du
  site en porte un.

## Publication

`.github/workflows/documentation.yml`
construit le site à chaque pull request touchant `documentation/` — un renvoi
mort y fait échouer la CI, `onBrokenLinks` étant réglé sur `throw` — et le publie
sur GitHub Pages à chaque `push` sur `main`, à l'adresse
[https://kederiku.github.io/juui/](https://kederiku.github.io/juui/).

Le déploiement se fait par artefact — rien n'est commité dans une branche
`gh-pages`.

Le workflow **active GitHub Pages lui-même** au premier passage
(`actions/configure-pages` avec `enablement: true`) : rien à cocher dans les
réglages du dépôt, et la chaîne se rejoue telle quelle sur un autre dépôt. Si une
politique d'organisation venait à refuser cette activation par API, elle se fait
à la main dans _Settings → Pages_, avec « GitHub Actions » comme source.

C'est le premier workflow du dépôt, et sa portée s'arrête à `documentation/` :
les pipelines de l'API, des frontends et des images reviennent aux tickets QA,
les règles de protection de branche à QA-08.

Les écarts assumés avec les tickets DOC-01 et DOC-02b sont consignés au
[registre des écarts](../ecarts/doc.md).
