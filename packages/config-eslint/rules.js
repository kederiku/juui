/**
 * Les decisions de regles de `@repo/eslint-config`, isolees de la plomberie.
 *
 * Les trois presets forment une chaine — `next` etend `react`, qui etend
 * `base` — et ce fichier est le seul endroit a modifier pour durcir ou
 * assouplir le socle. Deux portees s'y cotoient depuis SETUP-07, et il faut les
 * distinguer :
 *
 * - `sharedRules` est applique par `base`, donc par LES TROIS presets ;
 * - `a11yRules` et `a11yComponents` le sont par `react`, donc par `react` et
 *   `next` mais JAMAIS par `base` -- qui cible du Node sans JSX, ou des regles
 *   d'accessibilite n'auraient rien a regarder.
 *
 * Volontairement des objets de REGLES NUS, sans cle `plugins` : l'enregistrement
 * des plugins reste dans les presets, ce fichier ne porte que des arbitrages.
 *
 * Le socle est TYPE-AWARE depuis SETUP-06 : `base.js` applique
 * `tseslint.configs.recommendedTypeChecked` et branche le service de projet de
 * TypeScript. Les regles qui exigent un programme sont donc disponibles ici --
 * c'est ce que SETUP-03 avait annonce, puis laisse en suspens faute de mesure.
 * Ce que la bascule coute en temps est chiffre sur la page
 * « Configurations partagees » du site de documentation.
 */
export const sharedRules = {
  // `console.log` oublie en production ; warn et error restent legitimes.
  'no-console': ['warn', { allow: ['warn', 'error'] }],

  // Le prefixe `_` est la convention pour marquer un binding volontairement
  // inutilise (parametre de callback, element ignore d'un destructuring).
  '@typescript-eslint/no-unused-vars': [
    'error',
    {
      argsIgnorePattern: '^_',
      varsIgnorePattern: '^_',
      caughtErrorsIgnorePattern: '^_',
      destructuredArrayIgnorePattern: '^_',
    },
  ],

  // `import type` explicite : le transpileur peut effacer l'import sans avoir a
  // resoudre le module, ce dont dependent `isolatedModules` et Turbopack.
  '@typescript-eslint/consistent-type-imports': [
    'error',
    { prefer: 'type-imports', fixStyle: 'inline-type-imports' },
  ],

  // Tri des imports (le « tri des imports » du ticket SETUP-03).
  'import-x/order': [
    'warn',
    {
      groups: ['builtin', 'external', 'internal', 'parent', 'sibling', 'index', 'type'],
      pathGroups: [{ pattern: '@repo/**', group: 'internal', position: 'before' }],
      'newlines-between': 'always',
      alphabetize: { order: 'asc', caseInsensitive: true },
    },
  ],
  'import-x/no-duplicates': 'error',

  // Les deux regles qui exigent un resolveur capable de suivre les chemins
  // TypeScript. Elles attendaient FRONT-01, qui a apporte le premier tsconfig
  // d'application et, avec lui, les alias `@/*` et `@repo/ui/*` qu'une
  // resolution purement node ne suit pas. `base.js` branche desormais
  // eslint-import-resolver-typescript ; sans ce resolveur, ces deux regles
  // n'echoueraient pas -- elles ne verraient simplement rien.
  //
  // Un import casse est une erreur d'execution que rien d'autre n'attrape avant
  // le build : `tsc` ignore ce qui n'est pas type, et le lint est la seule passe
  // qui parcourt tous les fichiers du depot.
  'import-x/no-unresolved': 'error',
  // Un cycle d'imports ne casse pas toujours, et c'est ce qui le rend penible :
  // il rend l'ordre d'initialisation des modules dependant du point d'entree, si
  // bien que le meme code fonctionne en developpement et rend `undefined` une
  // fois groupe pour la production.
  'import-x/no-cycle': 'error',

  // La « comparaison toujours vraie » que vise SETUP-06 : un test dont le type
  // dit deja l'issue -- `if (obj)` sur un non-nullable, un `?.` sur ce qui ne
  // peut pas etre absent, un `catch` compare a une valeur impossible. Ce n'est
  // pas du style : un garde qui ne garde rien signale presque toujours que le
  // type et l'intention ont diverge.
  //
  // AJOUTEE A LA MAIN parce qu'elle n'est PAS dans `recommendedTypeChecked` --
  // elle appartient a `strictTypeChecked`, dont le reste est surtout
  // stylistique. La prendre seule vaut mieux que tirer tout le preset.
  //
  // Le `noUncheckedIndexedAccess` de @repo/typescript-config la rend tenable :
  // `tableau[i]` reste `T | undefined`, donc le test qui verifie un acces
  // indexe n'est jamais denonce comme inutile -- c'est le faux positif qui rend
  // cette regle insupportable sur les depots qui n'ont pas cette option.
  '@typescript-eslint/no-unnecessary-condition': 'error',
};

/**
 * Carte des composants de `@repo/ui` vers la balise que chacun rend reellement
 * (SETUP-07). Le preset `react` la donne a `settings['jsx-a11y-x'].components`.
 *
 * SANS ELLE, LES REGLES NE VOIENT RIEN. Le plugin raisonne sur des noms de
 * balises : le type d'un `<Input>` vaut « Input », pas « input », et aucune
 * regle ne se declenche sur un nom qui n'est celui d'aucun element HTML. Cette
 * carte joue donc pour l'accessibilite le role que le resolveur de `base.js`
 * joue pour import-x -- sans elle, les regles ne sont pas fausses, elles sont
 * muettes. Et comme les applications ne consomment presque que des composants
 * de `@repo/ui`, la carte est ce qui decide de leur couverture reelle.
 *
 * NE SONT MAPPES QUE LES COMPOSANTS DONT LA RACINE EST UNE BALISE FIXE.
 *
 * Les huit composants polymorphes du package en sont volontairement absents --
 * ceux qui rendent `Slot.Root` sous `asChild` : Button, Badge, BreadcrumbLink,
 * SidebarGroupLabel, SidebarGroupAction, SidebarMenuButton, SidebarMenuAction,
 * SidebarMenuSubButton. Leur racine depend d'une prop, que le plugin ne suit
 * pas : son reglage `polymorphicPropName` ne sait lire qu'une prop PORTANT un
 * nom de balise (`as="h3"`), la ou `asChild` delegue a l'enfant. Les mapper
 * fabriquerait des faux positifs de toutes pieces -- `BreadcrumbLink: 'a'`
 * ferait echouer `anchor-is-valid` sur le
 * `<BreadcrumbLink asChild><Link href=... /></BreadcrumbLink>` d'
 * admin-breadcrumb.tsx, dont le `href` est porte par l'enfant.
 *
 * Les primitives Radix (Dialog*, Select*, DropdownMenu*, Tooltip*) n'y figurent
 * pas davantage : ce sont des expressions membres (`DialogPrimitive.Root`), que
 * le plugin ignore d'office. C'est sans consequence -- elles portent deja leurs
 * roles et leurs attributs ARIA, c'est meme ce pour quoi Radix existe.
 */
export const a11yComponents = {
  // Formulaires. C'est de ces lignes que dependent
  // `label-has-associated-control` et `autocomplete-valid` -- les deux regles
  // qui comptent vraiment pour un parcours de prise de rendez-vous.
  Input: 'input',
  SidebarInput: 'input',
  Label: 'label',
  FieldSet: 'fieldset',
  FieldLegend: 'legend',

  // Titres. `heading-has-content` ne verrait rien d'un `<DialogTitle />` vide.
  DialogTitle: 'h2',
  SheetTitle: 'h2',

  // Tableau, ce que `scope` et `no-redundant-roles` attendent pour se prononcer.
  Table: 'table',
  TableHeader: 'thead',
  TableBody: 'tbody',
  TableFooter: 'tfoot',
  TableRow: 'tr',
  TableHead: 'th',
  TableCell: 'td',
  TableCaption: 'caption',

  // Reperes de page et listes.
  Breadcrumb: 'nav',
  BreadcrumbList: 'ol',
  BreadcrumbItem: 'li',
  SidebarMenu: 'ul',
  SidebarMenuSub: 'ul',
  SidebarMenuItem: 'li',
  SidebarMenuSubItem: 'li',
  SidebarInset: 'main',
};

/**
 * Arbitrages d'accessibilite, poses PAR-DESSUS le jeu `recommended` du plugin
 * (SETUP-07). Le preset `react` etale d'abord ce jeu, puis cet objet.
 *
 * VIDE, ET C'EST UN RESULTAT, PAS UN OUBLI. La premiere passe n'a releve qu'un
 * seul manquement sur tout le depot -- une limite d'analyse dans `field.tsx`,
 * traitee la-bas par une derogation a la ligne, motif ecrit. Aucune regle du
 * jeu recommande n'a eu a etre assouplie. Ecrire ici des arbitrages par
 * anticipation banaliserait l'objet : sa valeur tient a ce que chaque entree
 * corresponde a une gene reelle, constatee, et porte son motif.
 *
 * L'objet reste neanmoins etale par `react.js`, et c'est delibere : il garde
 * vraie la regle du depot -- le socle de regles se modifie en UN SEUL
 * endroit, ce fichier. Sans lui, le premier durcissement irait s'ecrire dans le
 * preset.
 */
export const a11yRules = {};

/**
 * Version de React declaree aux presets `react` et `next`.
 *
 * ESLint 10 a supprime `context.getFilename()`, sur lequel repose la detection
 * automatique (`"detect"`) d'eslint-plugin-react — embarque par
 * eslint-config-next. Sans cette valeur explicite, le lint plante.
 *
 * Figee par FRONT-01 : les trois applications epinglent react 19.2.8, comme
 * `packages/ui`. A remonter le jour ou elles changeront de mineure -- toutes
 * ensemble, ce socle etant partage.
 */
export const REACT_VERSION = '19.2';
