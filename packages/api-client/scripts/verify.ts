/**
 * SHARED-03 et FRONT-04 -- Preuve que le client genere appelle reellement l'API,
 * et que la couche de cache posee au-dessus se comporte comme annonce.
 *
 * CE QUE CE FICHIER PROUVE, ET CE QU'IL NE PROUVE PAS
 * Il appelle `checkLiveness` et `checkReadiness` -- les fonctions que les hooks
 * `useCheckLiveness` et `useCheckReadiness` appellent, a la ligne pres -- contre
 * le VRAI backend, et verifie que la donnee rendue porte bien la forme du
 * contrat. Il traverse donc toute la chaine : URL construite par Orval, mutator,
 * reseau, corps JSON, types.
 *
 * FRONT-04 y ajoute ce qui a besoin de `@tanstack/react-query` pour se prouver :
 * la politique de cache reellement posee, le predicat de reessai, l'appariement
 * PAR PREFIXE d'un vrai QueryCache, et le routage global des 401. L'algebre des
 * clefs, elle, se prouve hors ligne et sans rien installer --
 * `scripts/verify-query-keys.ts`, lance par `pnpm test`.
 *
 * Ce qu'il ne fait toujours pas, c'est RENDRE le hook : cela demande un runner
 * de test frontend, qui appartient a QA-02. L'ecart est consigne au registre.
 *
 * POURQUOI PAS UN DOUBLE DE L'API
 * Un serveur factice prouverait le mutator, pas le contrat : c'est justement la
 * derive entre le schema et le service que SHARED-03 existe pour rendre
 * impossible. La cible `make verify-api-client` exige donc `make dev`.
 */

/* eslint-disable no-console -- la sortie console EST le produit de ce programme :
   il n'a pas d'autre facon de rendre son verdict a qui lance `make
   verify-api-client`. La regle vise le code d'application, ou une trace oubliee
   part en production ; ce fichier ne quitte jamais le poste. */

import { ApiConfigurationError, ApiError, isApiError } from '../src/errors';
import {
  checkLiveness,
  checkReadiness,
  getCheckReadinessQueryKey,
} from '../src/generated/api/health/health';
import { createQueryClient, queryDefaultOptions } from '../src/query-client';
import {
  asClinicId,
  asGroupId,
  clinicQueryKey,
  groupQueryKey,
  publicQueryKey,
  tenantScopeKey,
} from '../src/query-keys';
import { dehydrate, getServerQueryClient } from '../src/query-server';
import {
  reportUnauthorized,
  resetUnauthorizedHandler,
  setUnauthorizedHandler,
} from '../src/unauthorized';

/** Un controle nomme, tel qu'il s'affiche a l'ecran. */
type Check = { name: string; run: () => Promise<string> };

const apiChecks: Check[] = [
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

/**
 * Fait croire au code appele qu'il tourne dans un navigateur, le temps d'un
 * controle.
 *
 * POURQUOI C'EST NECESSAIRE, ET POURQUOI CE N'EST PAS UN CONTOURNEMENT
 * Le predicat de reessai comme le routage des 401 refusent d'agir hors du
 * navigateur -- deux gardes deliberees, motivees dans query-client.ts et
 * unauthorized.ts : sur le serveur Next, un module est partage par toutes les
 * requetes du processus. Ce programme, lui, tourne dans Node. Sans cette
 * enveloppe, les controles ci-dessous ne verifieraient qu'une chose : que les
 * gardes mordent -- ce dont un controle s'occupe nommement, sans enveloppe.
 *
 * Asynchrone a dessein : `QueryCache.onError` n'est appele qu'apres la
 * resolution de la requete, et une enveloppe synchrone aurait deja retire
 * `window` a ce moment-la.
 */
async function withBrowserWindow<T>(run: () => Promise<T>): Promise<T> {
  const target = globalThis as { window?: unknown };
  target.window = {};
  try {
    return await run();
  } finally {
    delete target.window;
  }
}

/** Fabrique une ApiError comme le mutator en leve une. */
function apiError(status: number): ApiError {
  return new ApiError({
    status,
    code: 'identity.token.expired',
    message: `reponse ${String(status)}`,
    details: null,
    requestId: null,
  });
}

const GROUP_A = asGroupId('11111111-1111-1111-1111-111111111111');
const GROUP_B = asGroupId('22222222-2222-2222-2222-222222222222');
const CLINIC = asClinicId('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa');

const cacheChecks: Check[] = [
  {
    name: 'FRONT-04 : la clef recopiee par le programme hors ligne est celle d Orval',
    // LA JONCTION, et c'est le seul controle qui la tienne.
    // `scripts/verify-query-keys.ts` s'execute sans reseau, donc sans le code
    // genere : il recopie `['/health/ready']`. Si le backend renomme la route,
    // c'est ici que la recopie rougit -- la ou le code genere est disponible.
    run: () => {
      const generated = JSON.stringify(getCheckReadinessQueryKey());
      const copied = JSON.stringify(['/health/ready']);
      if (generated !== copied) {
        throw new Error(
          `scripts/verify-query-keys.ts recopie ${copied}, Orval exporte ${generated}`,
        );
      }
      return Promise.resolve(generated);
    },
  },
  {
    name: 'FRONT-04 : les defauts du cache sont ceux que le ticket demande',
    run: () => {
      const queries = queryDefaultOptions.queries;
      if (queries?.staleTime !== 60_000) {
        throw new Error(`staleTime attendu 60000, recu ${String(queries?.staleTime)}`);
      }
      if (queries.refetchOnWindowFocus !== false) {
        throw new Error('refetchOnWindowFocus n est plus desactive');
      }
      if (queryDefaultOptions.mutations?.retry !== false) {
        throw new Error('une mutation en echec serait rejouee');
      }
      return Promise.resolve('staleTime = 60 s, focus desactive, mutations jamais rejouees');
    },
  },
  {
    name: 'FRONT-04 : jamais de reessai sur un 4xx, oui sur un 5xx et sur un transport',
    run: () => {
      const retry = queryDefaultOptions.queries?.retry;
      if (typeof retry !== 'function') {
        throw new Error('le predicat de reessai a disparu des defauts');
      }
      const cases: [string, number, Error, boolean][] = [
        ['404', 0, apiError(404), false],
        ['401', 0, apiError(401), false],
        ['500', 0, apiError(500), true],
        ['transport (status 0)', 0, apiError(0), true],
        ['500 apres deux echecs', 2, apiError(500), false],
        ['configuration', 0, new ApiConfigurationError('base URL absente'), false],
        ['erreur quelconque', 0, new Error('inconnue'), false],
      ];
      return withBrowserWindow(() => {
        for (const [label, failureCount, error, expected] of cases) {
          if (retry(failureCount, error) !== expected) {
            throw new Error(`${label} : reessai attendu ${String(expected)}`);
          }
        }
        return Promise.resolve(`${String(cases.length)} cas conformes`);
      });
    },
  },
  {
    name: 'FRONT-04 : aucun reessai cote serveur, quel que soit le statut',
    // Sans enveloppe : ce programme EST hors navigateur. Le defaut « zero
    // tentative sur le serveur » de TanStack ne s'applique qu'en l'absence de
    // `retry` -- poser une fonction le neutralise, d'ou la garde explicite.
    run: () => {
      const retry = queryDefaultOptions.queries?.retry;
      if (typeof retry !== 'function') {
        throw new Error('le predicat de reessai a disparu des defauts');
      }
      if (retry(0, apiError(500)) || retry(0, apiError(0))) {
        throw new Error('un rendu serveur rejouerait la requete');
      }
      return Promise.resolve(
        'un 500 et un echec de transport ne sont pas rejoues au rendu serveur',
      );
    },
  },
  {
    name: 'FRONT-04 : deux QueryClient successifs sont deux instances',
    run: () => {
      if (createQueryClient() === createQueryClient()) {
        throw new Error('la fabrique rend un singleton : le cache serait partage');
      }
      return Promise.resolve('une instance par appel');
    },
  },
  {
    name: 'FRONT-04 : la purge d un groupe atteint ses clefs, et elles seules',
    // L'appariement PAR PREFIXE, joue sur un VRAI QueryCache : c'est lui qui
    // fait foi, la reproduction du programme hors ligne n'en est qu'un modele.
    run: () => {
      const operationKey = getCheckReadinessQueryKey();
      const client = createQueryClient();
      const cache = client.getQueryCache();

      client.setQueryData(groupQueryKey({ groupId: GROUP_A }, operationKey), {});
      client.setQueryData(clinicQueryKey({ groupId: GROUP_A, clinicId: CLINIC }, operationKey), {});
      client.setQueryData(groupQueryKey({ groupId: GROUP_B }, operationKey), {});
      client.setQueryData(publicQueryKey(operationKey), {});

      const scoped = cache.findAll({ queryKey: tenantScopeKey({ groupId: GROUP_A }) });
      if (scoped.length !== 2) {
        throw new Error(
          `2 entrees attendues dans le groupe A, ${String(scoped.length)} trouvee(s)`,
        );
      }

      client.removeQueries({ queryKey: tenantScopeKey({ groupId: GROUP_A }) });
      const left = cache.getAll();
      if (left.length !== 2) {
        throw new Error(`2 entrees devaient survivre, ${String(left.length)} restante(s)`);
      }
      if (cache.findAll({ queryKey: tenantScopeKey({ groupId: GROUP_B }) }).length !== 1) {
        throw new Error('la purge du groupe A a emporte le groupe B');
      }

      // SANS CETTE LIGNE, CE PROGRAMME NE REND PLUS LA MAIN -- mesure, pas
      // supposition. Une entree sans observateur programme son eviction par un
      // `setTimeout` de gcTime, soit cinq minutes : le processus Node reste
      // vivant jusque-la. `clear()` detruit les entrees et leurs minuteries.
      client.clear();
      return Promise.resolve(
        '4 entrees posees, 2 purgees, le groupe voisin et la clef publique intacts',
      );
    },
  },
  {
    name: 'FRONT-04 : dix 401 simultanes ne declenchent qu un seul traitement',
    run: async () => {
      // UN TABLEAU PLUTOT QU'UN COMPTEUR, et ce n'est pas un detail de style :
      // TypeScript ne sait pas qu'un gestionnaire pose ici sera rappele, et
      // reduirait un `let handled = 0` a son literal -- la comparaison sortirait
      // en « Unnecessary conditional » (SETUP-06). Une longueur de tableau, elle,
      // reste un `number`. Et le tableau porte les erreurs recues, donc le
      // message d'echec dit lesquelles.
      const handled: ApiError[] = [];
      return withBrowserWindow(async () => {
        setUnauthorizedHandler((error) => {
          handled.push(error);
        });
        try {
          await Promise.all(Array.from({ length: 10 }, () => reportUnauthorized(apiError(401))));
          if (handled.length !== 1) {
            throw new Error(`un seul traitement attendu, ${String(handled.length)} declenche(s)`);
          }
          return `10 signalements, ${String(handled.length)} traitement`;
        } finally {
          resetUnauthorizedHandler();
        }
      });
    },
  },
  {
    name: 'FRONT-04 : seul un 401 declenche le traitement global',
    run: async () => {
      const handled: ApiError[] = [];
      return withBrowserWindow(async () => {
        setUnauthorizedHandler((error) => {
          handled.push(error);
        });
        try {
          await reportUnauthorized(apiError(403));
          await reportUnauthorized(apiError(500));
          await reportUnauthorized(new Error('pas une ApiError'));
          if (handled.length !== 0) {
            throw new Error(
              `aucun traitement attendu, recu ${handled.map((e) => String(e.status)).join(', ')}`,
            );
          }
          return '403, 500 et erreur quelconque ignores';
        } finally {
          resetUnauthorizedHandler();
        }
      });
    },
  },
  {
    name: 'FRONT-04 : un 401 traverse le QueryCache jusqu au traitement global',
    run: async () => {
      const handled: ApiError[] = [];
      return withBrowserWindow(async () => {
        setUnauthorizedHandler((error) => {
          handled.push(error);
        });
        try {
          const client = createQueryClient();
          await client
            .fetchQuery({
              queryKey: publicQueryKey(['front-04', 'sonde-401']),
              queryFn: () => {
                throw apiError(401);
              },
            })
            .catch(() => undefined);
          // Le traitement passe par une microtache : laisser la file se vider
          // avant de conclure.
          await new Promise<void>((resolve) => {
            setTimeout(resolve, 0);
          });
          // Meme raison que dans le controle de la purge : une entree en cache
          // porte une minuterie d'eviction qui retient le processus.
          client.clear();
          if (handled.length !== 1) {
            throw new Error('le QueryCache n a pas route le 401 vers le traitement global');
          }
          return 'QueryCache.onError -> reportUnauthorized -> gestionnaire';
        } finally {
          resetUnauthorizedHandler();
        }
      });
    },
  },
  {
    name: 'FRONT-04 : rien ne se declenche hors du navigateur',
    // Sans enveloppe, et c'est le controle qui prouve la garde elle-meme : le
    // gestionnaire pose dans ce module serait, cote serveur, celui d'un AUTRE
    // utilisateur que celui dont on rend la requete.
    run: async () => {
      const handled: ApiError[] = [];
      await withBrowserWindow(() => {
        setUnauthorizedHandler((error) => {
          handled.push(error);
        });
        return Promise.resolve();
      });
      try {
        await reportUnauthorized(apiError(401));
        if (handled.length !== 0) {
          throw new Error('un 401 recu au rendu serveur a declenche le traitement global');
        }
        return 'le 401 remonte a l appelant, sans effet de bord global';
      } finally {
        await withBrowserWindow(() => {
          resetUnauthorizedHandler();
          return Promise.resolve();
        });
      }
    },
  },
  {
    name: 'FRONT-04 : hors du navigateur, aucun gestionnaire ne peut meme etre pose',
    // La garde de setUnauthorizedHandler, et non plus seulement celle du
    // signalement : un module `'use client'` est execute au rendu serveur, ou
    // poser une fermeture sur la session d'un utilisateur l'ecrirait dans un
    // etat partage par tout le processus.
    run: async () => {
      const handled: ApiError[] = [];
      setUnauthorizedHandler((error) => {
        handled.push(error);
      });
      try {
        await withBrowserWindow(() => reportUnauthorized(apiError(401)));
        if (handled.length !== 0) {
          throw new Error('un gestionnaire pose au rendu serveur a ete retenu');
        }
        return 'la pose est refusee, le defaut reste en place';
      } finally {
        await withBrowserWindow(() => {
          resetUnauthorizedHandler();
          return Promise.resolve();
        });
      }
    },
  },
  {
    name: 'FRONT-04 : un gestionnaire qui leve ne remplace pas le 401 d origine',
    // Regression de la revue contradictoire : `Promise.resolve(handler(error))`
    // evaluait le gestionnaire AVANT d'attacher le .catch(), et une levee
    // synchrone traversait le cache en remplacant l'erreur affichee.
    run: async () => {
      return withBrowserWindow(async () => {
        setUnauthorizedHandler(() => {
          throw new Error('panne du gestionnaire de FRONT-07');
        });
        try {
          await reportUnauthorized(apiError(401));
          return 'la levee est capturee, l appelant garde son erreur';
        } finally {
          resetUnauthorizedHandler();
        }
      });
    },
  },
  {
    name: 'FRONT-04 : le client des composants serveur precharge et se deshydrate',
    // `query-server.ts` n'a aucun appelant dans le produit : sans ce controle,
    // le chemin d'hydratation serait documente sur une page entiere et prouve
    // par rien.
    run: async () => {
      const client = getServerQueryClient();
      if (getServerQueryClient() === client) {
        throw new Error('hors portee de requete React, la fabrique doit rendre une instance neuve');
      }
      await client.prefetchQuery({
        queryKey: publicQueryKey(getCheckReadinessQueryKey()),
        queryFn: () => Promise.resolve({ status: 'ready' }),
      });
      const state = dehydrate(client);
      if (state.queries.length !== 1) {
        throw new Error(
          `1 requete deshydratee attendue, ${String(state.queries.length)} trouvee(s)`,
        );
      }
      client.clear();
      return `deshydrate ${JSON.stringify(state.queries[0]?.queryKey)}`;
    },
  },
];

/**
 * SHARED-03 d'abord -- la chaine reelle jusqu'au backend --, FRONT-04 ensuite.
 * L'ordre est celui du diagnostic : une pile eteinte se voit sur les trois
 * premiers, et les suivants ne dependent d'aucun reseau.
 */
const checks: Check[] = [...apiChecks, ...cacheChecks];

async function main(): Promise<void> {
  console.log('SHARED-03 et FRONT-04 : verification du client genere et de sa couche de cache.\n');

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
    console.error(`SHARED-03 et FRONT-04 : ${String(failed)} controle(s) en echec.`);
    process.exitCode = 1;
    return;
  }
  console.log(`SHARED-03 et FRONT-04 : ${String(checks.length)} controles passes.`);
}

void main();
