/**
 * SHARED-03 -- Preuve que le client genere appelle reellement l'API.
 *
 * CE QUE CE FICHIER PROUVE, ET CE QU'IL NE PROUVE PAS
 * Il appelle `checkLiveness` et `checkReadiness` -- les fonctions que les hooks
 * `useCheckLiveness` et `useCheckReadiness` appellent, a la ligne pres -- contre
 * le VRAI backend, et verifie que la donnee rendue porte bien la forme du
 * contrat. Il traverse donc toute la chaine : URL construite par Orval, mutator,
 * reseau, corps JSON, types.
 *
 * Ce qu'il ne fait pas, c'est RENDRE le hook : cela demande un
 * QueryClientProvider, qui appartient a FRONT-04, et un runner de test frontend,
 * qui appartient a QA-02. L'ecart est consigne au registre.
 *
 * POURQUOI PAS UN DOUBLE DE L'API
 * Un serveur factice prouverait le mutator, pas le contrat : c'est justement la
 * derive entre le schema et le service que ce ticket existe pour rendre
 * impossible. La cible `make verify-api-client` exige donc `make dev`.
 */

/* eslint-disable no-console -- la sortie console EST le produit de ce programme :
   il n'a pas d'autre facon de rendre son verdict a qui lance `make
   verify-api-client`. La regle vise le code d'application, ou une trace oubliee
   part en production ; ce fichier ne quitte jamais le poste. */

import { isApiError } from '../src/errors';
import { checkLiveness, checkReadiness } from '../src/generated/api/health/health';

import type { ApiError } from '../src/errors';

/** Un controle nomme, tel qu'il s'affiche a l'ecran. */
type Check = { name: string; run: () => Promise<string> };

const checks: Check[] = [
  {
    name: 'checkLiveness rend un LivenessReport type',
    run: async () => {
      const report = await checkLiveness();
      // ELARGI A `string` A DESSEIN. `report.status` est type par le litteral
      // "alive" : TypeScript sait donc que la comparaison est toujours fausse,
      // et le lint le dirait. On la fait quand meme, car c'est precisement
      // l'ecart entre ce que le type PROMET et ce que le service TRANSMET que
      // ce controle mesure -- un type ne verifie rien a l'execution.
      const status: string = report.status;
      if (status !== 'alive') {
        throw new Error(`status attendu "alive", recu "${status}"`);
      }
      return `status = ${status}`;
    },
  },
  {
    name: 'checkReadiness rend un ReadinessReport et ses composants',
    run: async () => {
      const report = await checkReadiness();
      const { postgres, redis } = report.components;
      return `status = ${report.status}, postgres = ${postgres}, redis = ${redis}`;
    },
  },
  {
    name: 'une route inconnue leve une ApiError normalisee',
    run: async () => {
      // Le mutator est appele comme le fait le code genere : une URL relative et
      // un RequestInit. La route n'existe pas -- Starlette rend un 404, que les
      // handlers de BACK-09 traduisent dans le format unique.
      const { customFetch } = await import('../src/mutator');
      try {
        await customFetch('/api/v1/cette-route-n-existe-pas', { method: 'GET' });
      } catch (error) {
        // `cause` sur chacune : la regle `preserve-caught-error` du socle
        // (SETUP-06) veut qu'une erreur relevee garde celle qui l'a declenchee.
        // Ici c'est utile pour de bon -- l'ApiError d'origine porte le code, le
        // statut et l'identifiant de requete que le message resume.
        if (!isApiError(error)) {
          throw new Error(`ApiError attendue, recu ${String(error)}`, { cause: error });
        }
        const normalized: ApiError = error;
        if (normalized.status !== 404) {
          throw new Error(`statut 404 attendu, recu ${String(normalized.status)}`, {
            cause: error,
          });
        }
        // BACK-11 expose X-Request-ID au JavaScript : l'absence d'identifiant
        // ici signalerait que l'intergiciel de correlation ne l'expose plus.
        if (normalized.requestId === null) {
          throw new Error('aucun identifiant de requete : X-Request-ID n est plus expose ?', {
            cause: error,
          });
        }
        return `code = ${normalized.code}, request_id present`;
      }
      throw new Error('aucune erreur levee sur une route inconnue');
    },
  },
];

async function main(): Promise<void> {
  console.log('SHARED-03 : verification du client genere contre l API reelle.\n');

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
    console.error(`SHARED-03 : ${String(failed)} controle(s) en echec.`);
    process.exitCode = 1;
    return;
  }
  console.log(`SHARED-03 : ${String(checks.length)} controles passes.`);
}

void main();
