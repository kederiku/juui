---
title: Configurations partagées
description: Les quatre packages de configuration — ESLint, Prettier, TypeScript, Tailwind — et la chaîne de presets qui les relie.
---

# Configurations partagées

Quatre packages portent la configuration commune du monorepo — ESLint, Prettier,
TypeScript et Tailwind. Chacun expose des presets que les workspaces étendent en
quelques lignes, et chaque règle ne se modifie qu'à un seul endroit.

| Package                   | Rôle                                                                 |
| ------------------------- | -------------------------------------------------------------------- |
| `@repo/eslint-config`     | Presets ESLint : `base`, `react`, `next`.                            |
| `@repo/prettier-config`   | Configuration Prettier, ré-exportée par `prettier.config.mjs`.       |
| `@repo/typescript-config` | Trois `tsconfig` : `base.json`, `react-library.json`, `nextjs.json`. |
| `@repo/tailwind-config`   | Le thème Tailwind v4 du dépôt, et la chaîne PostCSS.                 |

Les trois presets ESLint forment une chaîne — `next` étend `react`, qui étend
`base` — et partagent donc exactement le même socle de règles :

- **`base`** — TypeScript et Node, sans rien de spécifique à React. Pour
  `packages/*` et les scripts d'outillage.
- **`react`** — `base`, plus les règles des hooks, plus les 31 règles
  d'accessibilité (SETUP-07). Pour `packages/ui` (SHARED-01), qui est du React
  sans Next.
- **`next`** — `react` plus les 22 règles de `@next/eslint-plugin-next`. Pour les
  trois applications (FRONT-01 et suivants).

Une application les consomme ainsi :

```js
// frontend/frontend-professional/eslint.config.mjs
import next from '@repo/eslint-config/next';
import { defineConfig, globalIgnores } from 'eslint/config';

export default defineConfig([globalIgnores(['.next/**']), ...next]);
```

La ré-exclusion locale de `.next/` n'est pas redondante avec celle de la racine :
la recherche de configuration partant du fichier analysé, ce fichier **remplace**
celui de la racine pour son workspace — ses exclusions comprises.

Le socle de règles se modifie en un seul endroit :
`packages/config-eslint/rules.js`.

Le preset `base` y branche aussi le **résolveur d'imports** — la variante
TypeScript, seule à lire les `paths` des `tsconfig` et la carte `exports` des
packages du dépôt. C'est ce qui donne leur objet à `import-x/no-unresolved` et
`import-x/no-cycle` : sans résolveur, ces deux règles ne signalent jamais rien.

La liste des `tsconfig` qu'il reçoit suit `pnpm-workspace.yaml`, mais elle est
**développée par `base.js` lui-même**, `fs.globSync` ancré sur la racine du
dépôt. Lui passer les motifs tels quels — ce que faisait la première version — le
laisse les développer depuis le **répertoire de travail**, et il écarte alors le
`tsconfig` du dossier où l'on se trouve : un `eslint .` lancé dans
`frontend/frontend-admin` recevait les trois autres `tsconfig` du dépôt et pas le
sien, donc ne résolvait plus un seul `@/*`. La panne était invisible depuis la
racine, qui n'est le dossier d'aucun workspace — c'est le genre de défaut qu'on
ne voit qu'en changeant de répertoire.

**Depuis SETUP-06, ce socle est _type-aware_.** `base.js` applique
`tseslint.configs.recommendedTypeChecked` et branche le service de projet de
TypeScript (`parserOptions.projectService`). Le lint dispose donc des types, et
attrape ce qu'une analyse purement syntaxique ne peut pas voir : une promesse
jamais attendue, une comparaison que le type rend toujours vraie, une opération
sur un `any` qui s'ignore.

La frontière est nette — **tout `.ts` et `.tsx` est typé, aucun `.js` ni `.mjs`
ne l'est.** Ce n'est pas un arbitrage de confort, c'est l'état du dépôt : les
`include` des trois applications ne retiennent que les `.ts` et les `.tsx`, celui
de `packages/ui` et de `packages/api-client` que leurs sources sous `src/`, et
**aucun des quatre packages de configuration** n'a de `tsconfig.json` —
`config-typescript` ne porte que des presets, `base.json`, `nextjs.json` et
`react-library.json`, qu'aucun projet ne désigne comme sien. Aucun fichier JavaScript n'appartient
donc à un projet TypeScript, et le bloc `base-untyped` de `base.js` les en
dispense explicitement. Sans lui, chacun de ces fichiers JavaScript sort en
`Parsing error: […] was not found by the project service` — le parseur s'arrête
avant même de lire le code, à commencer par les quatre fichiers de configuration
de la racine.

Ce que la bascule a coûté, **mesuré à la livraison de SETUP-06** (66 fichiers
lintés alors : 49 en TypeScript, 17 en JavaScript), médiane de trois passes :

| Mesure                                                | Avant  | Après  |
| ----------------------------------------------------- | ------ | ------ |
| `pnpm lint` — le dépôt entier                         | 0,9 s  | 3,6 s  |
| `eslint --fix` sur un `.ts` — ce que lance le hook    | 0,5 s  | 1,3 s  |
| `eslint --fix` sur trois fichiers de trois workspaces | 0,6 s  | 2,2 s  |
| `eslint --fix` sur un `.mjs` — hors typage            | 0,44 s | 0,45 s |

La dernière ligne est la vérification du bloc `base-untyped` : un fichier
JavaScript ne fait construire aucun programme, et son lint ne bouge pas d'un
centième. La troisième est celle qui compte pour le [hook de
pre-commit](../getting-started/conventions-du-depot.md#hooks-de-pre-commit) —
deux secondes environ, contre un budget de dix.

**Depuis SETUP-07, il porte aussi l'accessibilité.** Trente et une règles, sur
le preset `react` — donc sur `packages/ui` **et**, par héritage, sur les trois
applications. C'est `packages/ui` qui porte les composants : c'est là qu'un
manquement se fabrique, et là qu'il doit se voir.

Le paquet est [`eslint-plugin-jsx-a11y-x`](https://github.com/es-tooling/eslint-plugin-jsx-a11y-x),
et non `eslint-plugin-jsx-a11y`. Ce dernier n'a rien publié depuis octobre 2024
et plafonne toujours sa peer `eslint` à `^9` — c'est le motif exact de son
retrait en SETUP-03, vérifié avant d'être contourné. La variante annonce
`^9 || ^10`. **Même famille, et même raisonnement, que le remplacement
d'`eslint-plugin-import` par `import-x`** : on ne force pas une peer, on prend le
paquet qui dit la vérité sur ce qu'il supporte. D'où le préfixe `jsx-a11y-x/` sur
les règles, et la clé `settings['jsx-a11y-x']` sur les réglages.

La pièce qui fait tout le travail est la **carte de correspondance**,
`a11yComponents` (`packages/config-eslint/rules.js`) : vingt-trois composants de
`@repo/ui` associés à la balise que chacun rend réellement — `Input` → `input`,
`Label` → `label`, `TableHead` → `th`, `DialogTitle` → `h2`… Sans elle les règles
ne sont pas fausses, elles sont **muettes** : le plugin raisonne sur des noms de
balises, et le type d'un `<Input>` vaut « Input ». Comme les applications ne
consomment presque que des composants de `@repo/ui`, cette carte est ce qui
décide de leur couverture réelle. Elle joue ici le rôle que le résolveur
d'imports joue pour `import-x`.

**N'y figure que ce dont la racine est une balise fixe.** Les huit composants
polymorphes — ceux qui rendent `Slot.Root` sous `asChild` : `Button`, `Badge`,
`BreadcrumbLink`, `SidebarGroupLabel`, `SidebarGroupAction`,
`SidebarMenuButton`, `SidebarMenuAction`, `SidebarMenuSubButton` — en sont
volontairement absents. Leur racine dépend d'une prop que le plugin ne sait pas
suivre : son réglage `polymorphicPropName` ne lit qu'une prop **portant** un nom
de balise (`as="h3"`), là où `asChild` délègue à l'enfant. Les mapper
fabriquerait des faux positifs de toutes pièces — `BreadcrumbLink: 'a'` ferait
échouer `anchor-is-valid` sur le `<BreadcrumbLink asChild><Link href=… /></BreadcrumbLink>`
d'`admin-breadcrumb.tsx`, dont le `href` est porté par l'enfant. Les primitives
Radix (`Dialog*`, `Select*`, `DropdownMenu*`, `Tooltip*`) n'y sont pas
davantage : ce sont des expressions membres, que le plugin ignore d'office, et
elles portent déjà leurs rôles ARIA — c'est ce pour quoi Radix existe.

Le jeu retenu est `recommended`, et **aucune règle n'a été écartée** :
`a11yRules` (`packages/config-eslint/rules.js`) est vide, ce qui est un résultat
et non un oubli. La première passe n'a relevé qu'un seul manquement sur tout le
dépôt, et c'était une limite d'analyse plutôt qu'un défaut :
`label-has-associated-control` exige de tout label un `htmlFor` ou un contrôle
descendant, or `FieldLabel` (`packages/ui/src/components/field.tsx`) n'est qu'un
emballage — les deux lui arrivent par `{...props}`, que le plugin ne sait pas
lire. La règle a le même angle mort sur le **texte** du label, mais elle y
présume l'inverse et se tait ; c'est cette asymétrie qu'on rencontre. D'où une
dérogation **à la ligne**, motif écrit sur place, et une seule dans tout le
dépôt. La règle reste pleinement active partout ailleurs — sur chaque `<Label>`
et chaque `<FieldLabel>` réellement posés dans une page, le seul endroit où un
champ peut vraiment se retrouver sans étiquette.

Le coût est négligeable, et il a été mesuré comme le reste : `pnpm lint` passe de
3,64 s à 3,74 s, un `.tsx` de 1,06 s à 1,11 s — un dixième de seconde, sans
commune mesure avec la bascule type-aware du ticket précédent. Le budget de dix
secondes du [hook de
pre-commit](../getting-started/conventions-du-depot.md#hooks-de-pre-commit)
n'en est pas entamé.

Que les règles soient bien actives se vérifie d'une ligne, en introduisant le
manquement le plus banal qui soit :

```bash
echo '<img src="/juui.png" />' # inséré dans une page, puis : pnpm lint
```

`jsx-a11y-x/alt-text` sort en `error`, `pnpm lint` rend 1, et le hook de
pre-commit interrompt le commit — c'est vérifié à chaque fois que ce socle bouge.

## `@repo/typescript-config`

Même principe, une chaîne : `react-library.json` et `nextjs.json` étendent tous
deux `base.json`.

| Fichier              | Pour qui                                     | Ce qu'il ajoute                                                                                                                                                                   |
| -------------------- | -------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `base.json`          | personne directement                         | Le socle : cible ES2023, résolution `bundler`, et le mode strict complet — `strict`, `noUncheckedIndexedAccess`, `noImplicitOverride`, `verbatimModuleSyntax`, `isolatedModules`. |
| `react-library.json` | `packages/ui`                                | `jsx: react-jsx` et les bibliothèques `DOM`.                                                                                                                                      |
| `nextjs.json`        | les trois applications (FRONT-01 à FRONT-03) | `jsx: preserve` — le JSX est laissé à SWC —, le plugin d'éditeur `next`, `allowJs` et `incremental`.                                                                              |

Un consommateur se réduit à ceci :

```json
// packages/ui/tsconfig.json
{
  "extends": "@repo/typescript-config/react-library.json",
  "compilerOptions": { "paths": { "@repo/ui/*": ["./src/*"] } },
  "include": ["src/**/*.ts", "src/**/*.tsx"],
  "exclude": ["node_modules", "dist"]
}
```

**`include`, `exclude` et `paths` restent chez lui**, et ce n'est pas un oubli :
TypeScript résout les chemins relatifs d'un `tsconfig` _relativement au fichier
de configuration dont ils proviennent_. Un `include` posé dans `base.json`
désignerait `packages/config-typescript`, jamais le projet qui hérite.

## `@repo/tailwind-config`

Tailwind v4 n'a plus de `tailwind.config.js`, donc plus de preset au sens de la
v3 : un thème partagé **est** un fichier CSS que l'on importe.
`packages/config-tailwind/theme.css` tient ce rôle et porte tout — palette
claire et sombre, échelle de rayons, typographie, variante `.dark`. C'est le
seul fichier du dépôt où une couleur est écrite ; en changer une y repeint les
trois applications et `@repo/ui`.

Une application n'y touche jamais : elle importe `@repo/ui/globals.css`, qui
n'est qu'un renvoi vers ce fichier.

La ligne à ne pas perdre de vue :

```css
@source '../ui/src/**/*.{ts,tsx}';
```

C'est le `content` d'autrefois. Tailwind ignore `node_modules` dans sa détection
automatique — et c'est précisément par un lien symbolique de `node_modules`
qu'une application atteint `@repo/ui`. Sans cette ligne, **toutes** les classes
des composants seraient purgées du CSS final. Le chemin est résolu relativement
à `theme.css`, d'où `../ui/src`.

La chaîne PostCSS vit dans le même package ; les trois applications la
ré-exportent au lieu de la réécrire :

```js
// frontend/frontend-professional/postcss.config.mjs
export { default } from '@repo/tailwind-config/postcss.config';
```

Enfin, la typographie est un **contrat**, pas une police : le preset déclare
`--font-sans: var(--font-juui-sans, …)`, à charge pour chaque application
d'alimenter `--font-juui-sans` avec `next/font`. `frontend-professional` y charge
Geist depuis FRONT-01, en sans et en mono ; une application qui ne le ferait pas
retomberait sur la valeur de repli, sans rien casser.

Les écarts assumés avec les tickets SHARED-02, SETUP-06 et SETUP-07 sont consignés au
registre des écarts — pages [SHARED](../ecarts/shared.md) et [SETUP](../ecarts/setup.md).
