/**
 * SHARED-03 -- FICHIER GENERE PAR ORVAL. NE PAS EDITER.
 * Source : packages/api-client/openapi.json, exporte depuis l'API FastAPI.
 * Regeneration :  make generate-api
 * Sortie versionnee (ADR-0007) : un diff ici est un changement de contrat.
 */
import {
  useQuery
} from '@tanstack/react-query';
import type {
  DataTag,
  DefinedInitialDataOptions,
  DefinedUseQueryResult,
  QueryClient,
  QueryFunction,
  QueryKey,
  UndefinedInitialDataOptions,
  UseQueryOptions,
  UseQueryResult
} from '@tanstack/react-query';

import type {
  ErrorResponse
} from '../model/error-response';

import type {
  LivenessReport
} from '../model/liveness-report';

import type {
  ReadinessReport
} from '../model/readiness-report';

import { customFetch } from '../../../mutator';
import type { ErrorType } from '../../../mutator';


type SecondParameter<T extends (...args: never) => unknown> = Parameters<T>[1];



const withQueryKey = <T extends object, K>(query: T, queryKey: K): T & { queryKey: K } => {
  const result = { queryKey } as T & { queryKey: K };
  for (const key of Object.keys(query)) {
    // The explicit queryKey always wins, matching the previous
    // `{ ...query, queryKey }` spread where it was set last.
    if (key === 'queryKey') continue;
    Object.defineProperty(result, key, {
      enumerable: true,
      configurable: true,
      get: () => (query as Record<string, unknown>)[key],
    });
  }
  return result;
};

export const getCheckLivenessUrl = () => {




  return `/health/live`
}

/**
 * Repond immediatement, sans toucher a aucune dependance externe.
 *
 * Returns:
 *     Le rapport de vie -- toujours le meme : si cette fonction s'execute,
 *     le processus est vivant.
 * @summary Sonde de vie
 */
export const checkLiveness = async ( options?: Parameters<typeof customFetch>[1]): Promise<LivenessReport> => {

  return customFetch<LivenessReport>(getCheckLivenessUrl(),
  {
    ...options,
    method: 'GET'


  }
);}





export const getCheckLivenessQueryKey = () => {
    return [
    `/health/live`
    ] as const;
    }


export const getCheckLivenessQueryOptions = <TData = Awaited<ReturnType<typeof checkLiveness>>, TError = ErrorType<unknown>>( options?: { query?:Partial<UseQueryOptions<Awaited<ReturnType<typeof checkLiveness>>, TError, TData>>, request?: SecondParameter<typeof customFetch>}
) => {

const {query: queryOptions, request: requestOptions} = options ?? {};

  const queryKey =  queryOptions?.queryKey ?? getCheckLivenessQueryKey();



    const queryFn: QueryFunction<Awaited<ReturnType<typeof checkLiveness>>> = ({ signal }) => checkLiveness({ signal, ...requestOptions });





   return  { queryKey, queryFn, ...queryOptions} as UseQueryOptions<Awaited<ReturnType<typeof checkLiveness>>, TError, TData> & { queryKey: DataTag<QueryKey, TData, TError> }
}

export type CheckLivenessQueryResult = NonNullable<Awaited<ReturnType<typeof checkLiveness>>>
export type CheckLivenessQueryError = ErrorType<unknown>


export function useCheckLiveness<TData = Awaited<ReturnType<typeof checkLiveness>>, TError = ErrorType<unknown>>(
  options: { query:Partial<UseQueryOptions<Awaited<ReturnType<typeof checkLiveness>>, TError, TData>> & Pick<
        DefinedInitialDataOptions<
          Awaited<ReturnType<typeof checkLiveness>>,
          TError,
          Awaited<ReturnType<typeof checkLiveness>>
        > , 'initialData'
      >, request?: SecondParameter<typeof customFetch>}
 , queryClient?: QueryClient
  ):  DefinedUseQueryResult<TData, TError> & { queryKey: DataTag<QueryKey, TData, TError> }
export function useCheckLiveness<TData = Awaited<ReturnType<typeof checkLiveness>>, TError = ErrorType<unknown>>(
  options?: { query?:Partial<UseQueryOptions<Awaited<ReturnType<typeof checkLiveness>>, TError, TData>> & Pick<
        UndefinedInitialDataOptions<
          Awaited<ReturnType<typeof checkLiveness>>,
          TError,
          Awaited<ReturnType<typeof checkLiveness>>
        > , 'initialData'
      >, request?: SecondParameter<typeof customFetch>}
 , queryClient?: QueryClient
  ):  UseQueryResult<TData, TError> & { queryKey: DataTag<QueryKey, TData, TError> }
export function useCheckLiveness<TData = Awaited<ReturnType<typeof checkLiveness>>, TError = ErrorType<unknown>>(
  options?: { query?:Partial<UseQueryOptions<Awaited<ReturnType<typeof checkLiveness>>, TError, TData>>, request?: SecondParameter<typeof customFetch>}
 , queryClient?: QueryClient
  ):  UseQueryResult<TData, TError> & { queryKey: DataTag<QueryKey, TData, TError> }
/**
 * @summary Sonde de vie
 */

export function useCheckLiveness<TData = Awaited<ReturnType<typeof checkLiveness>>, TError = ErrorType<unknown>>(
  options?: { query?:Partial<UseQueryOptions<Awaited<ReturnType<typeof checkLiveness>>, TError, TData>>, request?: SecondParameter<typeof customFetch>}
 , queryClient?: QueryClient
 ):  UseQueryResult<TData, TError> & { queryKey: DataTag<QueryKey, TData, TError> } {

  const queryOptions = getCheckLivenessQueryOptions(options)

  const query = useQuery(queryOptions, queryClient) as  UseQueryResult<TData, TError> & { queryKey: DataTag<QueryKey, TData, TError> };

  return withQueryKey(query, queryOptions.queryKey);
}






export const getCheckReadinessUrl = () => {




  return `/health/ready`
}

/**
 * Interroge PostgreSQL et Redis, et repond 503 si l'un des deux manque.
 *
 * Les deux sondes partent EN PARALLELE : le pire cas vaut le maximum des deux
 * delais (10 s cote moteur, 2 s cote Redis), pas leur somme.
 *
 * Le parametre `response` est le mecanisme FastAPI qui laisse poser le code
 * 503 tout en gardant `ReadinessReport` comme modele de reponse unique -- le
 * corps a la meme forme en panne et en sante, seul le code change.
 *
 * Args:
 *     response: la reponse en construction, pour y poser le code.
 *     database: les ressources de persistance du `lifespan`.
 *     cache: le cache du `lifespan`, reduit a son PING.
 *     settings: la configuration, pour nommer la cible en cas d'echec.
 *
 * Returns:
 *     Le rapport, composant par composant.
 * @summary Sonde de disponibilite
 */
export const checkReadiness = async ( options?: Parameters<typeof customFetch>[1]): Promise<ReadinessReport> => {

  return customFetch<ReadinessReport>(getCheckReadinessUrl(),
  {
    ...options,
    method: 'GET'


  }
);}





export const getCheckReadinessQueryKey = () => {
    return [
    `/health/ready`
    ] as const;
    }


export const getCheckReadinessQueryOptions = <TData = Awaited<ReturnType<typeof checkReadiness>>, TError = ErrorType<ErrorResponse | ReadinessReport>>( options?: { query?:Partial<UseQueryOptions<Awaited<ReturnType<typeof checkReadiness>>, TError, TData>>, request?: SecondParameter<typeof customFetch>}
) => {

const {query: queryOptions, request: requestOptions} = options ?? {};

  const queryKey =  queryOptions?.queryKey ?? getCheckReadinessQueryKey();



    const queryFn: QueryFunction<Awaited<ReturnType<typeof checkReadiness>>> = ({ signal }) => checkReadiness({ signal, ...requestOptions });





   return  { queryKey, queryFn, ...queryOptions} as UseQueryOptions<Awaited<ReturnType<typeof checkReadiness>>, TError, TData> & { queryKey: DataTag<QueryKey, TData, TError> }
}

export type CheckReadinessQueryResult = NonNullable<Awaited<ReturnType<typeof checkReadiness>>>
export type CheckReadinessQueryError = ErrorType<ErrorResponse | ReadinessReport>


export function useCheckReadiness<TData = Awaited<ReturnType<typeof checkReadiness>>, TError = ErrorType<ErrorResponse | ReadinessReport>>(
  options: { query:Partial<UseQueryOptions<Awaited<ReturnType<typeof checkReadiness>>, TError, TData>> & Pick<
        DefinedInitialDataOptions<
          Awaited<ReturnType<typeof checkReadiness>>,
          TError,
          Awaited<ReturnType<typeof checkReadiness>>
        > , 'initialData'
      >, request?: SecondParameter<typeof customFetch>}
 , queryClient?: QueryClient
  ):  DefinedUseQueryResult<TData, TError> & { queryKey: DataTag<QueryKey, TData, TError> }
export function useCheckReadiness<TData = Awaited<ReturnType<typeof checkReadiness>>, TError = ErrorType<ErrorResponse | ReadinessReport>>(
  options?: { query?:Partial<UseQueryOptions<Awaited<ReturnType<typeof checkReadiness>>, TError, TData>> & Pick<
        UndefinedInitialDataOptions<
          Awaited<ReturnType<typeof checkReadiness>>,
          TError,
          Awaited<ReturnType<typeof checkReadiness>>
        > , 'initialData'
      >, request?: SecondParameter<typeof customFetch>}
 , queryClient?: QueryClient
  ):  UseQueryResult<TData, TError> & { queryKey: DataTag<QueryKey, TData, TError> }
export function useCheckReadiness<TData = Awaited<ReturnType<typeof checkReadiness>>, TError = ErrorType<ErrorResponse | ReadinessReport>>(
  options?: { query?:Partial<UseQueryOptions<Awaited<ReturnType<typeof checkReadiness>>, TError, TData>>, request?: SecondParameter<typeof customFetch>}
 , queryClient?: QueryClient
  ):  UseQueryResult<TData, TError> & { queryKey: DataTag<QueryKey, TData, TError> }
/**
 * @summary Sonde de disponibilite
 */

export function useCheckReadiness<TData = Awaited<ReturnType<typeof checkReadiness>>, TError = ErrorType<ErrorResponse | ReadinessReport>>(
  options?: { query?:Partial<UseQueryOptions<Awaited<ReturnType<typeof checkReadiness>>, TError, TData>>, request?: SecondParameter<typeof customFetch>}
 , queryClient?: QueryClient
 ):  UseQueryResult<TData, TError> & { queryKey: DataTag<QueryKey, TData, TError> } {

  const queryOptions = getCheckReadinessQueryOptions(options)

  const query = useQuery(queryOptions, queryClient) as  UseQueryResult<TData, TError> & { queryKey: DataTag<QueryKey, TData, TError> };

  return withQueryKey(query, queryOptions.queryKey);
}






