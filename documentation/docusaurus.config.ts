import type * as Preset from '@docusaurus/preset-classic';
import type { Config } from '@docusaurus/types';
import type { PluginOptions as LocalSearchOptions } from '@easyops-cn/docusaurus-search-local';

/**
 * Configuration du site de documentation technique (DOC-01).
 *
 * Le site est en MODE « DOCS-ONLY » : la documentation est servie a la racine
 * (`routeBasePath: '/'`), il n'y a ni blog ni page vitrine. C'est un site
 * interne, lu par des developpeurs et par des agents ; une page d'accueil
 * marketing serait un fichier de plus a maintenir pour un lecteur qui cherche
 * une reponse, pas une presentation.
 *
 * Le CONTENU viendra ensuite -- DOC-02a pour l'architecture, DOC-02b pour les
 * ADR, DOC-02c pour le guide de contribution. Ce fichier livre le contenant :
 * l'arborescence, la barre laterale, la recherche et les diagrammes.
 */
const config: Config = {
  title: 'Juui',
  tagline: 'Documentation technique de la plateforme veterinaire',

  /*
   * LES QUATRE CHAMPS QU'EXIGE GITHUB PAGES. Le site est publie en « site de
   * projet » : `url` porte le domaine du compte, `baseUrl` le nom du depot.
   * Une erreur ici ne casse rien en local -- `docusaurus start` sert toujours
   * depuis la racine -- mais brise TOUS les liens et toutes les ressources une
   * fois en ligne. C'est le piege classique du premier deploiement.
   */
  url: 'https://kederiku.github.io',
  baseUrl: '/juui/',
  organizationName: 'kederiku',
  projectName: 'juui',
  /*
   * Explicite, et pas `undefined` : GitHub Pages ajoute une barre finale aux
   * URLs de Docusaurus par defaut, ce que la documentation de deploiement
   * recommande de trancher plutot que de subir.
   */
  trailingSlash: false,

  // Un lien mort casse le build, ici comme en CI. Une documentation dont les
  // renvois internes ne repondent plus est pire qu'une documentation absente :
  // elle fait perdre du temps avant d'avouer qu'elle est perimee.
  onBrokenLinks: 'throw',
  onBrokenAnchors: 'throw',

  // Site francais. Le theme livre ses propres traductions pour cette locale :
  // « Suivant », « Sur cette page », le libelle de la recherche.
  i18n: {
    defaultLocale: 'fr',
    locales: ['fr'],
  },

  markdown: {
    // Ce qui fait rendre les blocs ```mermaid comme des diagrammes, en paire
    // avec le theme declare plus bas. Les deux sont necessaires.
    mermaid: true,
    hooks: {
      // Et NON `onBrokenMarkdownLinks` a la racine, deprecie en Docusaurus 3.9
      // et promis a disparaitre en 4.
      onBrokenMarkdownLinks: 'throw',
    },
  },

  themes: [
    // Diagrammes Mermaid : l'architecture hexagonale et les flux se documentent
    // en texte versionne, pas en images binaires qu'aucun diff ne sait relire.
    '@docusaurus/theme-mermaid',

    [
      /*
       * RECHERCHE LOCALE, SANS AUCUN SERVICE EXTERNE -- ce que demande le
       * ticket. L'index est construit au `build` et sert depuis le site
       * lui-meme : ni compte Algolia, ni cle d'API, ni requete sortante.
       *
       * COROLLAIRE A CONNAITRE : la barre de recherche ne fonctionne PAS sous
       * `docusaurus start`. Le plugin n'y produit pas d'index et le dit dans la
       * console. Elle se verifie sur un `build` suivi d'un `serve`.
       *
       * Le paquet est designe par son NOM et non par `require.resolve` comme le
       * montre son README : `require` n'existe pas dans un module ES, et
       * Docusaurus resout deja les themes depuis le repertoire du site -- ou
       * pnpm a bien lie ce paquet, qui est une dependance directe.
       */
      '@easyops-cn/docusaurus-search-local',
      {
        // L'empreinte du contenu entre dans le nom du fichier d'index : le
        // navigateur peut le mettre en cache indefiniment sans jamais servir un
        // index perime.
        hashed: true,
        // Le francais d'abord, l'anglais parce que la moitie des termes
        // indexes sont des identifiants et des noms de paquets.
        language: ['fr', 'en'],
        // DOIT SUIVRE LE `routeBasePath` DES DOCS. Le defaut du plugin est
        // « /docs » : le laisser tel quel avec un site en mode docs-only
        // produirait un index vide, sans erreur.
        docsRouteBasePath: '/',
        // Il n'y a pas de blog a indexer.
        indexBlog: false,
        highlightSearchTermsOnTargetPage: true,
        explicitSearchResultPath: true,
      } satisfies LocalSearchOptions,
    ],
  ],

  presets: [
    [
      'classic',
      {
        docs: {
          // La documentation EST le site : pas de prefixe « /docs » dans les
          // URLs, et la premiere page (`slug: /`) est la page d'accueil.
          routeBasePath: '/',
          // Barre laterale ECRITE A LA MAIN, jamais deduite de l'arborescence :
          // c'est l'ordre de lecture qui prime, pas l'ordre alphabetique des
          // dossiers.
          sidebarPath: './sidebars.ts',
          // Par defaut Docusaurus retire un prefixe numerique du nom de
          // fichier (`0001-monorepo.md` -> id `monorepo`) : il le lit comme
          // un simple artifice de tri. Pour les ADR (DOC-02b), ce numero EST
          // l'identifiant de la decision -- il doit survivre dans l'id, l'URL
          // et les liens, sinon « ADR-0001 » ne serait citable nulle part.
          numberPrefixParser: false,
          editUrl: 'https://github.com/kederiku/juui/tree/main/documentation/',
        },
        blog: false,
      } satisfies Preset.Options,
    ],
  ],

  themeConfig: {
    navbar: {
      title: 'Juui',
      items: [
        {
          href: 'https://github.com/kederiku/juui',
          label: 'GitHub',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      copyright: 'Juui — documentation technique. Code publié sous licence MIT.',
    },
    colorMode: {
      // Suivre le reglage du systeme au premier chargement, comme le font les
      // trois applications avec next-themes.
      respectPrefersColorScheme: true,
    },
    mermaid: {
      // Deux themes, parce que le site en a deux : un diagramme lisible en
      // clair devient illisible sur fond sombre.
      theme: { light: 'neutral', dark: 'dark' },
    },
    prism: {
      // Les langages que le depot ecrit vraiment. Prism n'embarque par defaut
      // que le socle web ; sans cette liste, un bloc ```python sort en gris.
      additionalLanguages: ['bash', 'python', 'yaml', 'json', 'docker', 'ini'],
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
