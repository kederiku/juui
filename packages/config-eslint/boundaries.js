import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

/*
 * Racine du monorepo, deduite de l'emplacement de CE fichier -- et non du
 * repertoire de travail, qui vaut ce que vaut l'endroit d'ou l'on lance ESLint.
 * Meme ancrage, et meme motif, que celui de `base.js`.
 */
const repoRoot = fileURLToPath(new URL('../..', import.meta.url));

/*
 * Ce qui identifie une application Next : son dossier de routage. Le motif
 * `frontend/*` seul ramasserait aussi un `frontend/node_modules` le jour ou pnpm
 * en poserait un.
 */
const APPLICATIONS = 'frontend/*/app/';

/** Ou vivent les features d'une application, telles que FRONT-09 les place. */
const FEATURES = 'features';

/** Le dossier de routage : des pages qui composent, jamais de la logique. */
const ROUTING = 'app';

/**
 * Les dossiers de premier niveau qui ne sont NI du routage NI un domaine sont
 * transverses : `components/`, `lib/`, et tout ce qu'une application ajoutera.
 *
 * ILS SE DECOUVRENT, ILS NE S'ENUMERENT PAS. La premiere redaction les listait
 * en dur -- `['components', 'lib']` -- et la revue l'a mise en defaut : un
 * `hooks/` cree demain n'aurait ete ni `target` ni `from` d'aucune zone, donc
 * libre de lire l'interieur de n'importe quelle feature et de remonter dans
 * `app/`, en silence. Mesure : trois imports interdits y passaient sans un mot.
 *
 * Le monde est donc ferme, comme l'`exhaustive = true` des contrats de couches
 * de BACK-04b : ce qui n'est pas nomme n'est pas pour autant hors de portee.
 */
const NOT_TRANSVERSE = new Set([ROUTING, FEATURES]);

/** Ce qu'aucune enumeration de dossiers n'a a ramasser. */
const IGNORED_DIRECTORIES = new Set(['node_modules']);

/**
 * Les modules poses a la RACINE d'une application, `proxy.ts` en tete.
 *
 * Ecrit en glob, et pas en dossier : la racine de l'application contient aussi
 * `features/`, et un `target` pose sur elle ferait de chaque feature sa propre
 * cible -- elle se denoncerait a chaque import interne. Le glob ne retient que
 * les fichiers de premier niveau.
 */
const ROOT_MODULES = '*.{ts,tsx,js,mjs,cjs}';

/*
 * Les zones sont comparees par minimatch des qu'elles contiennent un caractere
 * de motif. Un chemin qui en porte un -- nom de depot, d'application ou de
 * feature -- verrait donc son motif relu de travers, et la regle deviendrait
 * MUETTE pour lui. On refuse bruyamment plutot que de laisser un garde-fou
 * s'eteindre sans bruit.
 *
 * LA CLASSE EST ETROITE, ET C'EST UNE CORRECTION DE REVUE. Elle interdisait
 * aussi `( ) ! + @`, qui ne sont des metacaracteres qu'en position d'extglob --
 * `+(...)`, `@(...)`. Mesure sur le minimatch reellement installe (10.2.6) : un
 * motif ancre sur « Projets (2) », « Projets+archives », « Projets@2 » ou
 * « !Projets » apparie parfaitement. La garde faisait donc echouer le
 * CHARGEMENT DE LA CONFIGURATION -- donc tout `pnpm lint` -- sur un depot clone
 * dans un dossier duplique par le Finder. Seuls `* ? [ ] { }` cassent
 * reellement l'appariement, verifie dans les deux sens.
 */
const GLOB_CHARACTERS = /[*?[\]{}]/;

/** Refuse un segment de chemin que minimatch relirait comme un motif. */
function assertLiteral(value, what) {
  if (GLOB_CHARACTERS.test(value)) {
    throw new Error(
      `FRONT-09 : ${what} « ${value} » contient un caractere de motif (*?[]{}). Les zones de frontiere seraient relues par minimatch et la regle deviendrait muette a son sujet.`,
    );
  }
}

/** Normalise un chemin en separateurs POSIX, ceux que minimatch attend. */
function toPosixPath(value) {
  return value.split(path.sep).join('/');
}

/** Developpe les sous-dossiers immediats d'un motif, tries. */
function directoriesMatching(root, pattern) {
  return fs
    .globSync(pattern, { cwd: root })
    .map((match) => toPosixPath(match).replace(/\/+$/, ''))
    .sort();
}

/**
 * Developpe les applications et leurs features, depuis le disque.
 *
 * LA LISTE N'EST PAS TENUE A LA MAIN, ET C'EST LE POINT. Elle se developpe a
 * chaque chargement de la configuration, comme `base.js` developpe deja celle
 * des tsconfig. Une feature ajoutee demain est gardee sans que personne ait
 * pense a l'inscrire quelque part -- c'est ce que le joker
 * `containers = ["app.modules.*"]` fait pour les contrats import-linter du
 * backend (BACK-04b), et la raison est la meme : une liste qu'il faut tenir
 * finit par ne plus l'etre, et le garde-fou s'eteint en silence.
 *
 * CE QUE CELA COUTE : la configuration est lue une fois. Un dossier de feature
 * cree pendant qu'un serveur ESLint tourne -- l'extension d'un editeur -- n'est
 * vu qu'au redemarrage de celui-ci. Meme comportement que la liste de tsconfig
 * de `base.js`, et meme remede.
 */
function discoverApplications(root) {
  return directoriesMatching(root, APPLICATIONS).map((routingPath) => {
    const applicationPath = path.posix.dirname(routingPath);
    const applicationName = path.posix.basename(applicationPath);

    assertLiteral(applicationName, "le nom d'application");

    const features = directoriesMatching(root, `${applicationPath}/${FEATURES}/*/`).map(
      (featurePath) => path.posix.basename(featurePath),
    );
    const transverse = directoriesMatching(root, `${applicationPath}/*/`)
      .map((directoryPath) => path.posix.basename(directoryPath))
      .filter((name) => !NOT_TRANSVERSE.has(name) && !IGNORED_DIRECTORIES.has(name));

    for (const feature of features) {
      assertLiteral(feature, 'le nom de feature');
    }
    for (const directory of transverse) {
      assertLiteral(directory, 'le nom de dossier transverse');
    }

    return { path: applicationPath, features, transverse };
  });
}

/**
 * Les zones d'une application, en trois familles.
 *
 * 1. L'INTERIEUR D'UNE FEATURE NE S'IMPORTE PAS DEPUIS L'EXTERIEUR. La surface
 *    publique d'une feature, ce sont les modules poses a sa RACINE ; ce qui vit
 *    dans un sous-dossier lui appartient en propre. C'est l'idiome du depot
 *    plutot qu'un baril `index.ts` : `@repo/ui` expose `./components/*` et
 *    `@repo/api-client` n'a pas d'export racine. Un baril obligerait en outre
 *    `proxy.ts`, qui n'a besoin que d'UN module d'identite, a passer par un
 *    fichier qui reexporte aussi les API serveur de la feature.
 *
 * 2. LE TRANSVERSE NE CONNAIT AUCUNE FEATURE, PAS MEME SA SURFACE. `components/`
 *    et `lib/` -- et tout autre dossier de premier niveau -- sont ce que les
 *    features partagent ; les laisser dependre de l'une d'elles inverserait la
 *    dependance et rendrait la barre laterale inutilisable sans le domaine
 *    qu'elle nomme.
 *
 * 3. PERSONNE NE REMONTE VERS `app/`. Le routage compose, il ne se consomme pas
 *    -- c'est le sens des fleches du contrat 5 de BACK-04b, `main > modules >
 *    shared > core`, transpose sur les espaces d'une application.
 *
 *    CE QU'ELLE REFERME N'EST PAS CE QU'ON CROIT, et la revue a corrige le
 *    motif : la famille 1 ne se contourne pas, son `target` nommant deja `app/`
 *    -- une page ne peut donc pas atteindre l'interieur d'une feature. C'est la
 *    famille 2 qui se contournerait en deux sauts : sans celle-ci, `components/`
 *    importerait une page, et une page importe legitimement une feature. Le
 *    transverse dependrait d'un domaine par transitivite, ce que
 *    `no-restricted-paths` ne voit pas -- elle ne juge qu'une arete a la fois.
 *
 * Le `target` d'une feature enumere ses SOEURS et les modules poses a la racine
 * de `features/`, jamais le dossier `features/` entier : celui-ci contiendrait
 * la feature elle-meme, qui se denoncerait a chaque import interne.
 *
 * CE QUE LA REGLE NE VOIT PAS : `typeof import('...')` en position de TYPE.
 * `moduleVisitor` ne visite pas les `TSImportType`. Le lint echoue quand meme --
 * `@typescript-eslint/consistent-type-imports` est en `error` dans `rules.js` et
 * refuse cette forme -- mais c'est un filet tenu par une AUTRE regle, qu'un
 * assouplissement futur rouvrirait. Verifie, et ecrit ici pour que la
 * dependance soit connue.
 */
function zonesForApplication({ path: applicationPath, features, transverse }) {
  const featuresPath = `${applicationPath}/${FEATURES}`;
  const routingPath = `${applicationPath}/${ROUTING}`;
  const transversePaths = transverse.map((directory) => `${applicationPath}/${directory}`);
  const rootModules = `${applicationPath}/${ROOT_MODULES}`;
  // Les modules poses directement dans `features/`, hors de toute feature. Sans
  // eux, un `features/shared.ts` lisait l'interieur de toutes les features --
  // mesure en revue.
  const featuresRootModules = `${featuresPath}/${ROOT_MODULES}`;

  const zones = features.map((feature) => ({
    target: [
      routingPath,
      ...transversePaths,
      rootModules,
      featuresRootModules,
      ...features
        .filter((sibling) => sibling !== feature)
        .map((sibling) => `${featuresPath}/${sibling}`),
    ],
    // `<feature>/*/**` : tout ce qui vit dans un SOUS-DOSSIER de la feature, et
    // rien de ce qui est pose a sa racine.
    from: `${featuresPath}/${feature}/*/**`,
    message: `interieur de la feature ${feature}. Passer par un module pose a la racine de ${featuresPath}/${feature}/, ou remonter le code partage d'un cran (FRONT-09).`,
  }));

  if (transversePaths.length > 0) {
    zones.push({
      target: transversePaths,
      from: featuresPath,
      message: `un module transverse (${transverse.join(', ')}) ne depend d'aucune feature. Deplacer ce code dans la feature qui l'utilise, ou le rendre generique (FRONT-09).`,
    });
  }

  zones.push({
    target: [featuresPath, ...transversePaths, rootModules],
    from: routingPath,
    message: `le routage compose, il ne se consomme pas. Deplacer ce que la page partage dans une feature ou dans un dossier transverse (FRONT-09).`,
  });

  return zones;
}

/**
 * La regle de frontiere des applications frontend (FRONT-09), prete a etre
 * etalee dans un preset.
 *
 * Rend un objet de REGLES NU -- meme forme que `rules.js`, et pour la meme
 * raison : l'enregistrement du plugin `import-x` reste dans `base.js`.
 *
 * `basePath` EST PASSE EXPLICITEMENT. La regle le fait defaut a `process.cwd()`,
 * ce qui suffirait tant que le lint part de la racine et deviendrait faux des
 * qu'un editeur le lance depuis le dossier du fichier ouvert -- les zones ne
 * designeraient alors plus rien, et la regle ne dirait plus rien non plus. Meme
 * panne, et meme parade, que les motifs de tsconfig de `base.js`.
 *
 * AUCUNE APPLICATION, AUCUNE REGLE : le schema de `no-restricted-paths` exige au
 * moins une zone. C'est le seul etat ou elle est muette, et
 * `scripts/verify-boundaries.js` en fait un controle a part entiere.
 *
 * @param {string} [root] Racine depuis laquelle chercher. Le defaut est la
 *   racine du depot ; le programme de verification passe la sienne.
 */
export function featureBoundaries(root = repoRoot) {
  assertLiteral(root, 'la racine du depot');

  const zones = discoverApplications(root).flatMap(zonesForApplication);

  if (zones.length === 0) {
    return {};
  }

  return {
    'import-x/no-restricted-paths': ['error', { basePath: root, zones }],
  };
}
