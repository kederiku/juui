/**
 * SHARED-03 -- Le mutator : l'unique porte de sortie HTTP du client genere.
 *
 * POURQUOI CE FICHIER EXISTE
 * Le code genere ne sait rien de l'environnement, ni de l'authentification, ni
 * du format d'erreur du service. Il sait construire une URL et un corps, et il
 * delegue tout le reste ICI. Ce que les trois applications partagent d'un appel
 * HTTP -- ou est l'API, qui l'appelle, ce qu'une erreur veut dire -- tient donc
 * dans ce seul fichier, et se corrige en un seul endroit.
 *
 * LA SIGNATURE N'EST PAS NEGOCIABLE
 * En client `fetch`, Orval appelle exactement :
 *   customFetch<Promise<checkLivenessResponse>>(getCheckLivenessUrl(), {
 *     ...options, method: 'GET' })
 * -- une URL DEJA construite (chemin et chaine de requete), et un `RequestInit`
 * qui porte deja le signal d'abandon de TanStack Query. Tout ce que ce fichier
 * ajoute se greffe autour ; rien ne remplace ce que le genere a decide.
 */

import { normalizeErrorResponse, transportFailure } from './errors/api-error';
import { readRequestIdentity, resolveBaseUrl } from './runtime';

import type { ApiError } from './errors/api-error';

/**
 * FRONT-10 -- Le type d'erreur des hooks generes, aligne sur ce qui est LEVE.
 *
 * ORVAL LIT CE NOM DANS CE FICHIER. Le generateur cherche litteralement
 * « export type ErrorType » dans le mutator ; s'il le trouve, chaque hook est
 * type `TError = ErrorType<...>` au lieu de deduire son erreur des reponses
 * declarees dans l'OpenAPI.
 *
 * CE QU'ON CORRIGE : la deduction est FAUSSE ici. Le code genere croyait que
 * `useCheckReadiness` echouait avec un `ReadinessReport` -- le modele du 503 --
 * alors que ce fichier leve une `ApiError` sur tout echec. Un appelant qui lisait
 * `error.status` compilait sur un type qui ne le porte pas. Depuis que le 500
 * est declare (FRONT-10), la deduction rendrait `ReadinessReport | ErrorResponse`,
 * c'est-a-dire le corps JSON brut : toujours faux, et plus credible.
 *
 * `_TBody` RESTE INUTILISE A DESSEIN, et le souligne le dit au lint comme au
 * lecteur : Orval passe la le corps qu'il a deduit de l'OpenAPI, dont
 * `ApiError` porte deja la substance -- `code`, `details`, et le corps brut
 * dans `rawBody`. Le parametre existe parce que le generateur ecrit
 * `ErrorType<...>`, pas parce qu'on en attend quelque chose.
 *
 * C'EST UNE ASSERTION, PAS UNE DEDUCTION, et la nuance a son cas : un ABANDON
 * de requete est re-leve tel quel un peu plus bas, donc un `DOMException`
 * traverse ce type. TanStack Query le traite comme une annulation et n'en fait
 * jamais un etat d'erreur -- aucun ecran ne le voit --, et `resolveApiError`
 * (FRONT-10) digere de toute facon ce qui n'est pas une `ApiError`.
 */
export type ErrorType<_TBody> = ApiError;

/**
 * Execute un appel a l'API : base URL, identite, erreurs normalisees.
 *
 * @param url Le chemin construit par le code genere, toujours commence par « / ».
 * @param options Le `RequestInit` du code genere -- methode, corps, en-tetes, et
 *   le signal d'abandon de TanStack Query.
 * @returns Le corps de la reponse, deja type par le code genere.
 * @throws ApiError sur toute reponse en echec ou tout echec de transport.
 * @throws ApiConfigurationError si la base URL manque a l'environnement.
 */
export async function customFetch<T>(url: string, options: RequestInit): Promise<T> {
  const identity = await readRequestIdentity();

  // `Headers` et non un objet nu : les en-tetes poses par le code genere -- le
  // Content-Type d'un corps JSON -- doivent survivre, et la casse ne doit pas
  // produire de doublon.
  const headers = new Headers(options.headers);
  headers.set('Accept', 'application/json');
  if (identity.token !== null) {
    headers.set('Authorization', `Bearer ${identity.token}`);
  }
  if (identity.clinicId !== null) {
    headers.set('X-Clinic-Id', identity.clinicId);
  }

  let response: Response;
  try {
    response = await fetch(`${resolveBaseUrl()}${url}`, {
      ...options,
      headers,
      // BACK-11 monte le CORS avec `allow_credentials=True`, et FRONT-07 posera
      // le jeton de rafraichissement en cookie httpOnly : sans cette ligne, ce
      // cookie ne partirait jamais, l'origine du frontend n'etant pas celle de
      // l'API.
      credentials: 'include',
    });
  } catch (cause) {
    // UN ABANDON N'EST PAS UNE ERREUR D'API. TanStack Query annule ses requetes
    // par AbortSignal et attend de retrouver SON exception : la deguiser en
    // ApiError afficherait une erreur a chaque navigation un peu rapide.
    if (options.signal?.aborted === true) {
      throw cause;
    }
    throw transportFailure(cause);
  }

  // Lisible par le JavaScript parce que EXPOSED_HEADERS l'y autorise (BACK-11).
  // Absent des reponses qui echappent au CORS -- d'ou le repli sur le corps,
  // dans normalizeErrorResponse.
  const requestId = response.headers.get('X-Request-ID');
  const payload = await readPayload(response);

  if (!response.ok) {
    throw normalizeErrorResponse({ status: response.status, requestId, payload });
  }

  return payload as T;
}

/**
 * Lit le corps d'une reponse sans jamais lever.
 *
 * TROIS CAS, ET AUCUN N'EST THEORIQUE :
 *   - un 204 (ou un 304) n'a PAS de corps : `text()` rend la chaine vide, et
 *     l'appelant doit recevoir `undefined`, pas une exception de parseur ;
 *   - un corps JSON, le cas ordinaire ;
 *   - un corps QUI N'EST PAS DU JSON -- la page d'erreur d'une passerelle, le
 *     « 400 Disallowed CORS origin » de Starlette. On le conserve tel quel :
 *     c'est `normalizeErrorResponse` qui decidera quoi en faire, et le texte
 *     brut reste consultable dans `error.rawBody`.
 */
async function readPayload(response: Response): Promise<unknown> {
  const raw = await response.text();
  if (raw === '') {
    return undefined;
  }
  try {
    return JSON.parse(raw) as unknown;
  } catch {
    return raw;
  }
}
