---
title: La bibliothèque @repo/ui
description: "La bibliothèque shadcn/ui en mode monorepo : identité visuelle, ajout d'un composant, DataTable et vérification du thème."
---

# La bibliothèque @repo/ui

Un seul package porte les composants, le thème et les utilitaires des trois
frontends — shadcn/ui en mode monorepo, exporté en source et jamais compilé :
identité visuelle, ajout d'un composant, `DataTable` et contrôle du thème.

`packages/ui` porte les composants, le thème et les utilitaires
partagés par les trois frontends. Le package n'est **jamais compilé** : il
s'exporte en source TypeScript, et chaque application le transpile.

| Chemin                   | Contenu                                                                           |
| ------------------------ | --------------------------------------------------------------------------------- |
| `src/components/`        | Composants shadcn/ui, `theme-provider.tsx`, `theme-toggle.tsx`, `data-table.tsx`. |
| `src/hooks/`             | Hooks partagés — `use-mobile.ts`, dont dépend la barre latérale.                  |
| `src/lib/utils.ts`       | `cn()` — fusion de classes Tailwind avec résolution des conflits.                 |
| `src/styles/globals.css` | Renvoi vers le thème partagé — le fichier qu'importe une application.             |
| `components.json`        | Configuration de la CLI shadcn en mode monorepo.                                  |

Les imports passent par la carte `exports` du package, jamais par un chemin
relatif :

```ts
import { Button } from '@repo/ui/components/button';
import { ThemeProvider } from '@repo/ui/components/theme-provider';
import { cn } from '@repo/ui/lib/utils';
```

## Identité visuelle

shadcn décrit un thème par quatre dimensions indépendantes. Celles de Juui :

| Dimension          | Valeur    | Où elle est inscrite                                      |
| ------------------ | --------- | --------------------------------------------------------- |
| Base de primitives | `radix`   | `components.json` — `"style": "radix-vega"`               |
| Style              | `vega`    | idem                                                      |
| Couleur de base    | `mist`    | `components.json` — `"baseColor": "mist"`, et `theme.css` |
| Couleur d'accent   | `emerald` | `theme.css` — `--primary`, `--ring`, `--sidebar-primary`  |

`pnpm dlx shadcn@4.19.0 info -c packages/ui` relit ces quatre valeurs depuis le
dépôt et doit répondre `vega` / `mist` / `emerald` — c'est le contrôle à faire
après toute retouche du thème.

Toutes les couleurs sont des variables CSS définies **une seule fois**, dans
`packages/config-tailwind/theme.css`.
Changer `--primary` y suffit à repeindre les trois applications ; aucune ne
redéfinit de couleur chez elle.

Le mode sombre est piloté par la classe `.dark` sur `<html>`, posée par le
`ThemeProvider` du package. Rien ne dépend de `prefers-color-scheme` : c'est ce
qui permet à l'utilisateur de choisir un thème indépendamment de son système.

## Ajouter un composant

Depuis la racine du dépôt, `-c packages/ui` désignant le workspace cible :

```bash
pnpm dlx shadcn@4.19.0 add tooltip -c packages/ui
```

Le fichier atterrit dans `packages/ui/src/components/`, ses imports réécrits en
`@repo/ui/...` grâce aux alias de `components.json`. Les variables de thème que
le registre apporte, elles, vont dans `packages/config-tailwind/theme.css` :
`components.json` désigne le preset, pas le `globals.css` du package — sans quoi
le thème recommencerait à se disperser. Le registre livre en guillemets doubles
et sans point-virgule : enchaîner systématiquement

```bash
pnpm format && pnpm lint:fix
```

**Épingler la version de la CLI** (`shadcn@4.19.0`) plutôt que `@latest` : une
version plus récente pourrait servir un autre style que `radix-vega` et faire
diverger le socle.

Le socle installé couvre Button, Input, Label, Card, Dialog, DropdownMenu,
Select, Sonner (notifications), Field (primitives de formulaire), Table, Badge,
Skeleton — plus Separator, tiré par Field. FRONT-03 y a ajouté Sidebar et
Breadcrumb, les deux primitives d'un back-office, avec ce que Sidebar réclame :
Sheet (son volet mobile), Tooltip (ses info-bulles une fois repliée) et le hook
`use-mobile`.

S'y ajoutent trois composants maison, absents du registre shadcn :
`theme-provider.tsx`, qui pose la classe `.dark`, `theme-toggle.tsx`, le bouton
qui la commande, et `data-table.tsx`, décrit juste après. Le deuxième a d'abord
vécu dans `frontend-professional` (FRONT-01) ; FRONT-02 l'a remonté ici plutôt
que de le recopier dans une deuxième application — c'est la règle que pose le
ticket, et la raison d'être du package.

### `DataTable` — la table de données

FRONT-03 demandait de **vérifier** que le composant `Table` couvrait le tri, le
filtrage et la pagination, et de créer une extension dans le package partagé
dans le cas contraire. Il ne les couvre pas : `table.tsx` est purement
présentationnel — huit composants qui habillent `<table>`, `<thead>`, `<tr>`,
sans le moindre état. Le registre shadcn n'a rien à proposer non plus, sa page
`data-table` étant un **guide** qui assemble ce même `table.tsx` avec TanStack
Table, et non un composant téléchargeable.

D'où `data-table.tsx` : `Table`
plus [TanStack Table](https://tanstack.com/table), avec tri par colonne
(`aria-sort` sur la cellule d'en-tête), filtre texte sur une colonne désignée et
pagination. L'appelant décrit ses colonnes, rien d'autre — l'état reste dans la
table :

```tsx
const column = createDataTableColumnHelper<Clinic>();
const columns = column.columns([column.accessor('name', { header: 'Clinique' })]);

<DataTable columns={columns} data={CLINICS} filterColumnId="name" pageSize={5} />;
```

**TanStack Table est en version 9, une réécriture** : les exemples que l'on
trouve en ligne, guide shadcn compris, sont écrits pour la 8 et ne fonctionnent
pas ici. Le hook s'appelle `useTable` et non `useReactTable`, les capacités
s'enregistrent dans un `tableFeatures` au lieu des options `getSortedRowModel()`,
et une cellule se rend avec `<table.FlexRender cell={…} />`. Le paquet embarque
ses propres consignes à jour, à lire plutôt que le web :

```bash
npx @tanstack/intent@latest list
```

Deux pièges tiennent au même mécanisme, l'enregistrement explicite. **Une
capacité non enregistrée n'existe pas** : sans `rowPaginationFeature`, il n'y a
ni état `pagination` ni méthode `setPageIndex`. Et **les fonctions de tri et de
filtrage ne sont pas globales** : une colonne en mode `auto` — le défaut —
résout un nom (`text`, `includesString`) dans les registres `sortFns` et
`filterFns`, qu'il faut déclarer. L'oubli ne casse pas de la même façon des deux
côtés, ce qui le rend pénible à diagnostiquer : le tri se rabat sur une
comparaison générique et **paraît** fonctionner, tandis que le filtre ne trouve
aucune fonction et laisse passer toutes les lignes — un champ de recherche qui
ne filtre rien, sans la moindre erreur. Les deux cas se signalent en console, en
développement seulement.

## Vérifier le thème sans lancer d'application

Une retouche du thème se contrôle sans démarrer quoi que ce soit, en le
compilant :

```bash
pnpm --filter @repo/ui run check:css
```

La sortie `packages/ui/dist/globals.built.css` (non versionnée) doit contenir
le bloc `:root`, le bloc `.dark`, et les classes utilisées par les composants du
package — signe que la directive `@source` fait bien son travail. Depuis
SHARED-02 la preuve est plus forte qu'elle n'en a l'air : le thème est atteint
**par le lien symbolique pnpm** de `node_modules`, exactement comme le fait
`frontend-professional`.

Le pendant du côté TypeScript, qui vérifie du même coup que l'héritage des
configurations partagées se résout :

```bash
pnpm typecheck
```

Les écarts assumés avec le ticket SHARED-01 sont consignés au
[registre des écarts](../ecarts/shared.md#écarts-assumés-avec-le-ticket-shared-01).
