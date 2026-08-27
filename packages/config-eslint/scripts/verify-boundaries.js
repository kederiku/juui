import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { ESLint } from 'eslint';
import { createTypeScriptImportResolver } from 'eslint-import-resolver-typescript';
import importX from 'eslint-plugin-import-x';
import tseslint from 'typescript-eslint';

import { featureBoundaries } from '../boundaries.js';

/**
 * FRONT-09 -- Preuve que la frontiere entre features est reellement tenue.
 *
 * CE QUE CE PROGRAMME PROUVE, ET POURQUOI IL EXISTE
 * Le critere d'acceptation dit « regle ESLint anti-import croise active ;
 * violation volontaire -> echec du lint (test) ». Le depot n'a AUCUN runner de
 * test frontend : Vitest et React Testing Library sont le perimetre de FRONT-06
 * et de QA-02. Meme arbitrage, et meme forme, que le `verify-query-keys.ts` de
 * FRONT-04 : un programme Node hors ligne, branche sur le script `test` du
 * package, donc ramasse par `pnpm test` et par `make test-front`.
 *
 * IL NE SIMULE PAS LA REGLE, IL LA JOUE. Les controles de conformite et de
 * violation tournent sur le VRAI depot, avec la configuration que les
 * applications chargent reellement : `lintText` recoit le chemin d'un fichier
 * existant et un contenu en memoire, si bien que la recherche de configuration
 * part du dossier de ce fichier -- donc de `frontend/<app>/eslint.config.mjs`,
 * donc du preset `next`. Aucun fichier n'est ecrit.
 *
 * DEUX PIEGES, ET CE QUI LES DESARME
 * 1. `no-restricted-paths` ne se declenche QUE si l'import se resout sur le
 *    disque : elle appelle `resolve()` et sort si le resultat est indefini. Une
 *    resolution cassee rendrait donc tous les controles negatifs vrais A VIDE,
 *    et ce programme annoncerait « conforme » sur un depot que personne n'a
 *    analyse. Chaque controle exige donc AUSSI zero `import-x/no-unresolved`.
 * 2. Le socle est type-aware : un fichier qu'aucun tsconfig ne couvre sort en
 *    erreur de PARSING, et un fichier qui ne parse pas n'est pas analyse du
 *    tout. Chaque controle exige donc zero message `fatal`.
 *
 * POURQUOI UNE ARBORESCENCE DE DEMONSTRATION MALGRE TOUT
 * La premiere famille de zones -- l'interieur d'une feature est prive -- ne peut
 * pas se prouver sur le vrai depot : aucune feature n'a encore de sous-dossier,
 * donc aucun import a viser, donc rien a resoudre. `fixtures/` porte les six
 * fichiers minimaux qui manquent, et le generateur de `boundaries.js` y est
 * applique tel quel, avec sa racine a elle.
 */

/* eslint-disable no-console -- la sortie console EST le produit de ce programme :
   il n'a pas d'autre facon de rendre son verdict a qui lance `pnpm test`. La
   regle vise le code d'application, ou une trace oubliee part en production ;
   ce fichier ne quitte jamais le poste et l'integration continue. */

/*
 * LES DEUX RACINES PASSENT PAR `path.resolve`, ET CE N'EST PAS COSMETIQUE.
 * `fileURLToPath(new URL('../../..', ...))` rend un chemin TERMINE PAR UNE BARRE
 * OBLIQUE, et un `cwd` ainsi forme fait echouer la resolution des alias `@/*` de
 * l'application : `import-x/no-unresolved` remonte alors sur chaque import
 * aliase, et `no-restricted-paths`, qui ne se declenche que sur un import
 * RESOLU, devient muette. Le programme annoncerait « conforme » sans avoir rien
 * analyse -- mesure, puis refermee. `path.resolve` normalise et retire la barre.
 */
const repoRoot = path.resolve(fileURLToPath(new URL('../../..', import.meta.url)));
const fixturesRoot = path.resolve(fileURLToPath(new URL('../fixtures', import.meta.url)));

/*
 * ON SE PLACE A LA RACINE DU DEPOT, ET C'EST INDISPENSABLE.
 * `pnpm --filter @repo/eslint-config test` lance ce programme depuis le dossier
 * du PACKAGE. Or le resolveur TypeScript retrouve le tsconfig d'une application
 * a partir du REPERTOIRE DE TRAVAIL, et non du `cwd` passe a `ESLint` : lance
 * depuis packages/config-eslint, il ne mappe plus un seul `@/*`, et
 * `no-restricted-paths` -- qui ne se declenche que sur un import RESOLU --
 * devient muette. Le programme annoncerait « conforme » sans avoir rien
 * analyse. Mesure, puis refermee ici. Meme famille de piege que les motifs de
 * glob de `base.js`, et meme parade : un chemin ancre, jamais devine.
 *
 * L'APPEL VIT DANS `main()`, ET NON ICI : un effet de bord qui partirait au
 * simple `import` de ce fichier serait une surprise, et `process.chdir` leve
 * `ERR_WORKER_UNSUPPORTED_OPERATION` dans un fil de travail -- ce que ces
 * controles deviendront le jour ou FRONT-06 les repliera dans Vitest.
 */

const BOUNDARY_RULE = 'import-x/no-restricted-paths';
const UNRESOLVED_RULE = 'import-x/no-unresolved';

/**
 * Les applications, DECOUVERTES et non enumerees.
 *
 * La premiere redaction les listait en dur, et la revue l'a mise en defaut deux
 * fois : une quatrieme application passait inapercue du controle de couverture,
 * et une quatrieme application pourtant conforme faisait echouer le controle en
 * accusant le generateur, qui avait raison. Une preuve qui contredit ce qu'elle
 * prouve n'est pas une preuve.
 */
const APPLICATIONS = fs
  .globSync('frontend/*/app/', { cwd: repoRoot })
  .map((match) => path.basename(path.dirname(match.replace(/\/+$/, ''))))
  .sort();

/** Un controle nomme, tel qu'il s'affiche a l'ecran. Meme forme que FRONT-04. */
/** @typedef {{ name: string, run: () => Promise<string> }} Check */

/**
 * Configuration des fixtures : la regle engendree par `boundaries.js`, et rien
 * d'autre.
 *
 * SANS TYPAGE, A DESSEIN. Le socle du depot est type-aware et les fixtures ne
 * sont couvertes par aucun tsconfig de workspace ; les analyser avec lui les
 * ferait sortir en erreur de parsing. `no-restricted-paths` ne raisonne que sur
 * des chemins : on ne perd rien. Le resolveur, lui, reste le meme que celui du
 * depot -- c'est lui qui suit l'alias `@/*`, sans quoi la regle serait muette.
 */
function fixtureConfiguration() {
  return [
    {
      files: ['**/*.{ts,tsx}'],
      languageOptions: {
        parser: tseslint.parser,
        parserOptions: { ecmaFeatures: { jsx: true }, projectService: false, project: false },
      },
      plugins: { 'import-x': importX },
      settings: {
        'import-x/resolver-next': [
          createTypeScriptImportResolver({
            alwaysTryTypes: true,
            project: [path.join(fixturesRoot, 'tsconfig.json')],
            noWarnOnMultipleProjects: true,
          }),
        ],
      },
      rules: {
        ...featureBoundaries(fixturesRoot),
        [UNRESOLVED_RULE]: 'error',
      },
    },
  ];
}

const realEslint = new ESLint({ cwd: repoRoot });
const fixtureEslint = new ESLint({
  cwd: fixturesRoot,
  overrideConfigFile: true,
  overrideConfig: fixtureConfiguration(),
});

/**
 * Analyse un import dans un fichier EXISTANT, sans jamais l'ecrire.
 *
 * Rend le nombre de violations de frontiere, apres avoir refuse les deux
 * facons de passer a vide -- import non resolu, fichier non parse.
 */
async function countBoundaryErrors(eslint, root, relativePath, importPath) {
  const code = `import * as proof from '${importPath}';\n\nexport default proof;\n`;
  const [result] = await eslint.lintText(code, { filePath: path.join(root, relativePath) });
  const messages = result?.messages ?? [];

  const fatal = messages.filter((message) => message.fatal);
  if (fatal.length > 0) {
    throw new Error(`${relativePath} n'a pas ete analyse : ${fatal[0]?.message ?? ''}`);
  }

  const unresolved = messages.filter((message) => message.ruleId === UNRESOLVED_RULE);
  if (unresolved.length > 0) {
    throw new Error(
      `l'import « ${importPath} » ne se resout pas depuis ${relativePath} : la regle ne peut rien voir, le controle serait vrai a vide`,
    );
  }

  return messages.filter((message) => message.ruleId === BOUNDARY_RULE).length;
}

/**
 * Exige qu'un import soit REFUSE.
 *
 * AU MOINS une violation, et non exactement une : les familles se recouvrent
 * legitimement -- un import de `components/` vers l'interieur d'une feature en
 * produit deux, une par famille. Exiger le compte exact aurait fait echouer un
 * cas pourtant correct, ce que la revue a mesure.
 */
async function expectRefused(eslint, root, relativePath, importPath) {
  const count = await countBoundaryErrors(eslint, root, relativePath, importPath);

  if (count < 1) {
    throw new Error(
      `${relativePath} -> ${importPath} : accepte alors qu'il franchit une frontiere`,
    );
  }
}

/** Exige qu'un import soit ACCEPTE. */
async function expectAllowed(eslint, root, relativePath, importPath) {
  const count = await countBoundaryErrors(eslint, root, relativePath, importPath);

  if (count !== 0) {
    throw new Error(`${relativePath} -> ${importPath} : refuse alors qu'il est legitime`);
  }
}

/** Les features reellement posees sur le disque, lues sans passer par le glob. */
function featuresOnDisk() {
  return APPLICATIONS.flatMap((application) => {
    const featuresPath = path.join(repoRoot, 'frontend', application, 'features');

    if (!fs.existsSync(featuresPath)) {
      return [];
    }

    return fs
      .readdirSync(featuresPath, { withFileTypes: true })
      .filter((entry) => entry.isDirectory())
      .map((entry) => `frontend/${application}/features/${entry.name}`);
  }).sort();
}

/** @type {Array<Check>} */
const checks = [
  {
    name: 'La regle est armee dans les trois applications',
    run: async () => {
      for (const application of APPLICATIONS) {
        const configuration = await realEslint.calculateConfigForFile(
          path.join(repoRoot, 'frontend', application, 'app', 'layout.tsx'),
        );
        const entry = configuration.rules?.[BOUNDARY_RULE];

        if (!entry) {
          throw new Error(`${application} : la regle n'est pas posee du tout`);
        }
        if (entry[0] !== 2 && entry[0] !== 'error') {
          throw new Error(`${application} : la regle avertit au lieu d'echouer`);
        }
        const zones = entry[1]?.zones ?? [];
        const covers = zones.some((zone) =>
          [zone.from].flat().some((from) => from.startsWith(`frontend/${application}/`)),
        );

        if (!covers) {
          throw new Error(`${application} : aucune zone ne la concerne`);
        }
      }

      return 'configuration reelle des trois applications, severite error, zones ancrees sur chacune';
    },
  },
  {
    name: 'Le code livre respecte ses propres frontieres',
    run: async () => {
      /*
       * UN SEUL MOTIF, ET LE PLUS LARGE POSSIBLE. La premiere redaction
       * enumerait app, features, components, lib et les seuls `.ts` poses a la
       * racine d'une application : elle reproduisait donc exactement l'angle mort
       * du generateur qu'elle etait censee couvrir -- un cinquieme dossier n'etait
       * pas analyse, et un `.tsx` pose a la racine non plus.
       */
      const results = await realEslint.lintFiles(['frontend/**/*.{ts,tsx,js,mjs,cjs}']);

      const messages = results.flatMap((result) =>
        result.messages.map((message) => ({ file: result.filePath, message })),
      );
      const offenders = messages.filter(
        ({ message }) =>
          message.fatal || message.ruleId === BOUNDARY_RULE || message.ruleId === UNRESOLVED_RULE,
      );

      if (offenders.length > 0) {
        const first = offenders[0];
        throw new Error(
          `${String(offenders.length)} probleme(s), a commencer par ${path.relative(repoRoot, first?.file ?? '')} : ${first?.message.message ?? ''}`,
        );
      }

      return `${String(results.length)} fichiers analyses, aucune frontiere franchie et aucun import irresolu`;
    },
  },
  {
    name: 'Le transverse ne peut pas importer une feature',
    run: async () => {
      await expectRefused(
        realEslint,
        repoRoot,
        'frontend/frontend-admin/components/navigation.ts',
        '@/features/identity/require-role',
      );
      await expectRefused(
        realEslint,
        repoRoot,
        'frontend/frontend-admin/lib/session.ts',
        '@/features/organization/clinics-table',
      );

      return "components/ et lib/ refuses sur la surface publique d'une feature";
    },
  },
  {
    name: 'Un import de TYPE est refuse comme un autre',
    run: async () => {
      const code =
        "import type { Session } from '@/features/identity/require-role';\n\nexport type Proof = Session;\n";
      const [result] = await realEslint.lintText(code, {
        filePath: path.join(repoRoot, 'frontend/frontend-admin/components/navigation.ts'),
      });
      const count = (result?.messages ?? []).filter(
        (message) => message.ruleId === BOUNDARY_RULE,
      ).length;

      if (count !== 1) {
        throw new Error(`${String(count)} violation(s) au lieu d'une seule sur un import de type`);
      }

      return "le couplage existe meme quand il ne coute rien a l'execution -- meme arbitrage que le exclude_type_checking_imports du backend";
    },
  },
  {
    name: 'Personne ne remonte vers app/',
    run: async () => {
      await expectRefused(
        realEslint,
        repoRoot,
        'frontend/frontend-admin/features/organization/clinics-table.tsx',
        '@/app/(protected)/page',
      );
      await expectRefused(
        realEslint,
        repoRoot,
        'frontend/frontend-admin/lib/session.ts',
        '@/app/(protected)/page',
      );

      return 'une feature et un module transverse refuses sur une page';
    },
  },
  {
    name: 'Ce qui est legitime reste silencieux',
    run: async () => {
      await expectAllowed(
        realEslint,
        repoRoot,
        'frontend/frontend-admin/app/(protected)/page.tsx',
        '@/features/organization/clinics-table',
      );
      await expectAllowed(
        realEslint,
        repoRoot,
        'frontend/frontend-admin/features/identity/require-role.ts',
        '@/lib/session',
      );
      await expectAllowed(
        realEslint,
        repoRoot,
        'frontend/frontend-admin/proxy.ts',
        '@/features/identity/require-role',
      );
      await expectAllowed(
        realEslint,
        repoRoot,
        'frontend/frontend-professional/features/health/service-status.tsx',
        '@repo/ui/components/badge',
      );

      return 'une page compose une feature, une feature lit lib/ et @repo/ui, le proxy garde son entree';
    },
  },
  {
    name: "L'interieur d'une feature est prive (arborescence de demonstration)",
    run: async () => {
      await expectRefused(
        fixtureEslint,
        fixturesRoot,
        'frontend/demo-app/features/beta/entry.ts',
        '@/features/alpha/internals/secret',
      );
      await expectRefused(
        fixtureEslint,
        fixturesRoot,
        'frontend/demo-app/app/page.ts',
        '@/features/alpha/internals/secret',
      );
      await expectRefused(
        fixtureEslint,
        fixturesRoot,
        'frontend/demo-app/components/shell.ts',
        '@/features/alpha/panel',
      );

      return 'une soeur, une page et le shell refuses sur un sous-dossier de feature';
    },
  },
  {
    name: 'La surface publique reste ouverte (arborescence de demonstration)',
    run: async () => {
      await expectAllowed(
        fixtureEslint,
        fixturesRoot,
        'frontend/demo-app/features/beta/entry.ts',
        '@/features/alpha/panel',
      );
      await expectAllowed(
        fixtureEslint,
        fixturesRoot,
        'frontend/demo-app/features/alpha/internals/secret.ts',
        '@/features/alpha/panel',
      );
      await expectAllowed(
        fixtureEslint,
        fixturesRoot,
        'frontend/demo-app/features/alpha/panel.ts',
        '@/features/alpha/internals/secret',
      );

      return 'une soeur passe par la racine, et la feature circule chez elle dans les deux sens';
    },
  },
  {
    name: 'Un cinquieme espace ne passe pas entre les mailles',
    run: async () => {
      await expectRefused(
        fixtureEslint,
        fixturesRoot,
        'frontend/demo-app/hooks/use-demo.ts',
        '@/features/alpha/internals/secret',
      );
      await expectRefused(
        fixtureEslint,
        fixturesRoot,
        'frontend/demo-app/hooks/use-demo.ts',
        '@/features/alpha/panel',
      );
      await expectRefused(
        fixtureEslint,
        fixturesRoot,
        'frontend/demo-app/features/shared.ts',
        '@/features/alpha/internals/secret',
      );

      return "un dossier de premier niveau que personne n'a nomme est transverse comme les autres, et un module pose a la racine de features/ n'ouvre aucun interieur";
    },
  },
  {
    name: 'Toute application produit ses zones',
    run: () => {
      if (APPLICATIONS.length === 0) {
        throw new Error('aucune application decouverte : le glob du programme ne trouve plus rien');
      }

      const zones = featureBoundaries(repoRoot)[BOUNDARY_RULE]?.[1]?.zones ?? [];
      const covered = new Set(
        zones.flatMap((zone) =>
          [zone.from]
            .flat()
            .map(
              (from) =>
                /^frontend\/(?<application>[^/]+)\//u.exec(String(from))?.groups?.application,
            )
            .filter((application) => application !== undefined),
        ),
      );
      const missing = APPLICATIONS.filter((application) => !covered.has(application));

      if (missing.length > 0) {
        throw new Error(`aucune zone ne concerne ${missing.join(', ')}`);
      }

      return `${String(APPLICATIONS.length)} applications decouvertes, toutes couvertes par au moins une zone`;
    },
  },
  {
    name: "Aucune feature n'echappe au generateur",
    run: () => {
      const zones = featureBoundaries(repoRoot)[BOUNDARY_RULE]?.[1]?.zones ?? [];

      if (zones.length === 0) {
        throw new Error(
          'le generateur ne rend aucune zone : la regle serait silencieusement inerte',
        );
      }

      const guarded = zones
        .map((zone) => /^(?<feature>.+)\/\*\/\*\*$/u.exec(String(zone.from))?.groups?.feature)
        .filter((feature) => feature !== undefined)
        .sort();
      const expected = featuresOnDisk();

      if (guarded.join('|') !== expected.join('|')) {
        throw new Error(
          `features gardees [${guarded.join(', ')}] mais posees sur le disque [${expected.join(', ')}]`,
        );
      }

      return `${String(expected.length)} features sur le disque, ${String(expected.length)} gardees`;
    },
  },
];

async function main() {
  process.chdir(repoRoot);
  console.log('FRONT-09 : verification des frontieres entre features.\n');

  let failed = 0;
  for (const check of checks) {
    try {
      const detail = await check.run();
      console.log(`  OK   ${check.name}\n       ${detail}`);
    } catch (error) {
      failed += 1;
      const reason = error instanceof Error ? error.message : String(error);
      console.error(`  ECHEC ${check.name}\n       ${reason}`);
    }
  }

  console.log('');
  if (failed > 0) {
    console.error(`FRONT-09 : ${String(failed)} controle(s) en echec.`);
    process.exitCode = 1;
    return;
  }
  console.log(`FRONT-09 : ${String(checks.length)} controles passes.`);
}

await main();
