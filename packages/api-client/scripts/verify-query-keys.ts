/**
 * FRONT-04 -- Preuve que la clef de cache isole les groupes.
 *
 * CE QUE CE PROGRAMME PROUVE, ET POURQUOI IL EXISTE
 * Le critere d'acceptation dit « les clefs de requete tenant incluent le groupe
 * actif (test de bascule) ». Le depot n'a AUCUN runner de test frontend : Vitest
 * et React Testing Library sont le perimetre de FRONT-06 et de QA-02, qui
 * DEPENDENT tous deux de ce ticket -- les poser ici, ce serait rendre a leur
 * place les cinq arbitrages qui font leur contenu.
 *
 * Il reste que la bascule se joue tout entiere dans la fabrique de clefs, et
 * que celle-ci est du TypeScript PUR. Node 24 efface les types a la volee :
 * `node scripts/verify-query-keys.ts` execute donc ce fichier et le module qu'il
 * verifie TELS QUELS -- sans compilation, sans pile demarree, sans dependance,
 * sans installation. C'est la preuve la moins chere disponible aujourd'hui, et
 * la seule qui tourne partout.
 *
 * CE QU'IL NE PROUVE PAS
 * Que la clef litterale utilisee ici est bien celle qu'Orval exporte : ce
 * fichier ne peut pas importer le code genere, qui remonte au mutator, donc au
 * reseau. C'est `scripts/verify.ts` qui tient cette JONCTION, ainsi que la
 * politique de cache et le routage des 401 -- eux ont besoin de
 * `@tanstack/react-query`.
 *
 * POURQUOI L'IMPORT PASSE PAR LE NOM DU PACKAGE, ET NON PAR `../src/`
 * Node reste un resolveur ESM : il exige une extension explicite, que les
 * imports relatifs du depot n'ecrivent jamais. L'AUTO-REFERENCE du package
 * (`@repo/api-client/query-keys`) contourne les deux ecueils d'un coup -- Node
 * lit la carte `exports` et y trouve le chemin complet, extension comprise,
 * tandis que TypeScript la lit aussi sous `moduleResolution: bundler`.
 *
 * ECRIRE `../src/query-keys.ts` AURAIT COUTE BIEN PLUS CHER, ET C'EST MESURE :
 * l'extension exige `allowImportingTsExtensions`, qu'ORVAL LIT AUSSI -- la
 * regeneration s'est alors mise a ecrire `from '../../../mutator.ts'` dans tout
 * le code genere, faisant echouer `make generate-api-check`, c'est-a-dire le
 * controle anti-derive de l'ADR-0007. Ne pas y revenir.
 */

/* eslint-disable no-console -- la sortie console EST le produit de ce programme :
   il n'a pas d'autre facon de rendre son verdict a qui lance `pnpm test`. La
   regle vise le code d'application, ou une trace oubliee part en production ;
   ce fichier ne quitte jamais le poste et l'integration continue. */

import {
  asClinicId,
  asGroupId,
  clinicQueryKey,
  groupQueryKey,
  publicQueryKey,
  tenantScopeKey,
} from '@repo/api-client/query-keys';

/** Un controle nomme, tel qu'il s'affiche a l'ecran. Meme forme que verify.ts. */
type Check = { name: string; run: () => string };

const GROUP_A = asGroupId('11111111-1111-1111-1111-111111111111');
const GROUP_B = asGroupId('22222222-2222-2222-2222-222222222222');
const CLINIC_1 = asClinicId('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa');
const CLINIC_2 = asClinicId('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb');

/**
 * La clef que produit `getCheckReadinessQueryKey()` d'Orval, recopiee.
 *
 * LA RECOPIE EST ASSUMEE, ET ELLE EST SURVEILLEE : `scripts/verify.ts` compare
 * cette constante a la clef reellement exportee par le code genere. Si le
 * backend renomme la route, c'est LA que le controle rougit.
 */
const OPERATION_KEY = ['/health/ready'] as const;

/**
 * Reproduit l'appariement PAR PREFIXE de TanStack Query pour les clefs plates
 * que produit la fabrique -- element par element, egalite stricte.
 *
 * Le comportement reel de la bibliotheque, lui, est verifie sur un vrai
 * QueryCache dans `scripts/verify.ts` : ici on n'a pas le droit d'importer
 * `@tanstack/react-query`, ce qui ferait tomber l'execution hors ligne.
 */
function matchesPrefix(key: readonly unknown[], prefix: readonly unknown[]): boolean {
  return prefix.length <= key.length && prefix.every((segment, index) => key[index] === segment);
}

const checks: Check[] = [
  {
    name: 'la clef d un groupe change avec le groupe actif (bascule)',
    run: () => {
      const a = JSON.stringify(groupQueryKey({ groupId: GROUP_A }, OPERATION_KEY));
      const b = JSON.stringify(groupQueryKey({ groupId: GROUP_B }, OPERATION_KEY));
      if (a === b) {
        throw new Error(`deux groupes distincts produisent la meme clef : ${a}`);
      }
      return `${a} != ${b}`;
    },
  },
  {
    name: 'la clef d Orval est reprise intacte, et en queue',
    run: () => {
      const key = groupQueryKey({ groupId: GROUP_A }, OPERATION_KEY);
      const tail = key.slice(key.length - OPERATION_KEY.length);
      if (JSON.stringify(tail) !== JSON.stringify(OPERATION_KEY)) {
        throw new Error(`la clef generee n est plus en queue : ${JSON.stringify(key)}`);
      }
      return JSON.stringify(key);
    },
  },
  {
    name: 'une clef publique ne porte aucune portee de tenance',
    run: () => {
      const key = publicQueryKey(OPERATION_KEY);
      if (matchesPrefix(key, tenantScopeKey({ groupId: GROUP_A }))) {
        throw new Error(
          `une clef publique tombe dans la portee d un groupe : ${JSON.stringify(key)}`,
        );
      }
      return JSON.stringify(key);
    },
  },
  {
    name: 'le prefixe de purge couvre le groupe et ses cliniques, et rien d autre',
    run: () => {
      const prefix = tenantScopeKey({ groupId: GROUP_A });
      const fromGroup = groupQueryKey({ groupId: GROUP_A }, OPERATION_KEY);
      const fromClinic = clinicQueryKey({ groupId: GROUP_A, clinicId: CLINIC_1 }, OPERATION_KEY);
      const fromOtherGroup = groupQueryKey({ groupId: GROUP_B }, OPERATION_KEY);

      if (!matchesPrefix(fromGroup, prefix) || !matchesPrefix(fromClinic, prefix)) {
        throw new Error('le prefixe ne couvre pas toutes les clefs du groupe');
      }
      if (matchesPrefix(fromOtherGroup, prefix)) {
        throw new Error('le prefixe deborde sur un autre groupe');
      }
      return `${JSON.stringify(prefix)} couvre le groupe et sa clinique, exclut le groupe voisin`;
    },
  },
  {
    name: 'deux cliniques d un meme groupe sont deux entrees distinctes',
    run: () => {
      const first = JSON.stringify(
        clinicQueryKey({ groupId: GROUP_A, clinicId: CLINIC_1 }, OPERATION_KEY),
      );
      const second = JSON.stringify(
        clinicQueryKey({ groupId: GROUP_A, clinicId: CLINIC_2 }, OPERATION_KEY),
      );
      if (first === second) {
        throw new Error(`deux cliniques distinctes produisent la meme clef : ${first}`);
      }
      return `${first} != ${second}`;
    },
  },
  {
    name: 'un identifiant vide est refuse plutot que range dans un seau commun',
    run: () => {
      // Blanche autant que vide : `['tenant', '   ', ...]` serait le meme seau
      // partage, et rien ne le signalerait a l'ecran.
      for (const blank of ['', '   ', '\t']) {
        let refused = false;
        try {
          asGroupId(blank);
        } catch {
          refused = true;
        }
        if (!refused) {
          throw new Error(`asGroupId a accepte ${JSON.stringify(blank)}`);
        }
      }
      let clinicRefused = false;
      try {
        asClinicId(' ');
      } catch {
        clinicRefused = true;
      }
      if (!clinicRefused) {
        throw new Error('asClinicId a accepte une chaine blanche');
      }
      return 'asGroupId et asClinicId refusent une chaine vide ou blanche';
    },
  },
];

function main(): void {
  console.log('FRONT-04 : verification de la portee des clefs de cache.\n');

  let failed = 0;
  for (const check of checks) {
    try {
      const detail = check.run();
      console.log(`  OK   ${check.name}\n       ${detail}`);
    } catch (error) {
      failed += 1;
      const reason = error instanceof Error ? error.message : String(error);
      console.error(`  ECHEC ${check.name}\n       ${reason}`);
    }
  }

  console.log('');
  if (failed > 0) {
    console.error(`FRONT-04 : ${String(failed)} controle(s) en echec.`);
    process.exitCode = 1;
    return;
  }
  console.log(`FRONT-04 : ${String(checks.length)} controles passes.`);
}

main();
