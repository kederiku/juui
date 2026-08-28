/**
 * SHARED-03, repris par FRONT-10 -- Les erreurs de l'API, telles que le
 * navigateur les voit.
 *
 * CE FICHIER NE CHOISIT AUCUN MESSAGE. Il normalise ; c'est `messages.ts`, a
 * cote, qui traduit un code en phrase lisible. La separation est le sujet meme
 * de FRONT-10 : `ApiError.message` est un message de JOURNAL, ecrit pour un
 * developpeur, et il ne s'affiche jamais.
 *
 * POURQUOI CE FICHIER EXISTE
 * BACK-09 promet UN format d'erreur, quatre clefs toujours presentes :
 * { code, message, details, request_id }. S'y fier aveuglement serait une faute,
 * car le backend documente lui-meme DEUX TROUS (BACK-11, registre des ecarts) :
 *   - un 500 ne traverse aucun intergiciel utilisateur -- il sort SANS en-tetes
 *     CORS, et le navigateur le presente au JavaScript comme un echec reseau ;
 *   - un preflight CORS refuse sort en « 400 Disallowed CORS origin », texte
 *     brut, hors format.
 * Une seule classe porte donc TOUJOURS les memes champs, que la reponse ait
 * respecte le contrat ou non : le code appelant n'a jamais a distinguer les deux
 * mondes.
 *
 * LE TYPE DU CORPS VIENT DU GENERE, ET C'EST FRONT-10 QUI L'A RENDU POSSIBLE
 * SHARED-03 avait du l'ecrire a la main : `ErrorResponse` n'etait declare que
 * sur le 422 du routeur v1, qui n'a encore aucune route, si bien que le
 * composant n'entrait pas dans l'OpenAPI. FRONT-10 a declare le 500 sur
 * `/health/ready` -- qui le produit reellement --, le composant est publie, et
 * ce fichier LIT desormais le contrat au lieu de le recopier. Un import de
 * TYPE : il disparait a la compilation, donc aucun couplage a l'execution, et
 * le module reste executable par Node sans compilation (voir `messages.ts`).
 *
 * SI LE BACKEND RECULAIT, la regeneration (`clean: true`) supprimerait le
 * fichier importe et la compilation tomberait. C'est voulu : une divergence de
 * contrat doit s'entendre.
 */

import type { ErrorResponse } from '../generated/api/model/error-response';

/**
 * Le corps d'erreur promis par BACK-09, tel que le contrat le publie.
 *
 * `code` et `message` sont exiges ; `details` et `request_id` portent un defaut
 * cote Pydantic et sortent donc FACULTATIFS du schema, alors que les handlers
 * les serialisent toujours. Le contrat publie etant plus permissif que la
 * promesse, c'est lui qu'on suit -- `normalizeErrorResponse` n'exige de toute
 * facon que les deux premiers.
 */
export type ApiErrorBody = ErrorResponse;

/**
 * Codes fabriques PAR LE CLIENT, quand le serveur n'en a pas fourni.
 *
 * Le prefixe les rend reconnaissables d'un coup d'oeil : ce qui commence par un
 * nom de module backend (`identity.`, `organization.`) vient du serveur, ce qui
 * commence par `api_client.` vient d'ici -- et ne se cherche donc pas dans les
 * journaux de l'API.
 */
export const CLIENT_ERROR_CODES = {
  /** Aucune reponse n'est parvenue : reseau, DNS, 500 sans CORS, preflight refuse. */
  unreachable: 'api_client.transport.unreachable',
  /** Une reponse est arrivee, hors du format d'erreur de BACK-09. */
  malformed: 'api_client.response.malformed',
  /**
   * Le deploiement est faux -- une base URL absente (FRONT-10).
   *
   * Pose par `resolveApiError` et non par le mutator : c'est une
   * `ApiConfigurationError` qui remonte, et elle n'est deliberement PAS une
   * `ApiError`. Le code n'existe donc que pour l'affichage.
   */
  configuration: 'api_client.configuration.invalid',
  /** Ce qui a ete attrape n'est pas une erreur d'API reconnaissable (FRONT-10). */
  unrecognized: 'api_client.error.unrecognized',
} as const;

/*
 * CE REGISTRE ET LA TABLE DE `messages.ts` SE TIENNENT PAR UNE SONDE, ET NON PAR
 * UN IMPORT. `messages.ts` ne peut rien importer en VALEUR -- c'est ce qui le
 * rend executable par Node sans compilation, et son en-tete le motive. Les deux
 * fichiers recopient donc les memes chaines, et `scripts/verify-errors.ts`
 * verifie que chaque code declare ici a bien son message la-bas.
 */

/**
 * Configuration inutilisable -- une base URL absente.
 *
 * UNE CLASSE A PART, ET NON UNE ApiError. L'API n'a rien refuse : c'est le
 * deploiement qui est faux. Confondre les deux ferait avaler une panne de
 * configuration par le `catch` qui affiche « reessayer », et personne ne
 * reessaierait avec succes.
 */
export class ApiConfigurationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ApiConfigurationError';
  }
}

/** Toute erreur rendue par l'API, ramenee a une forme unique. */
export class ApiError extends Error {
  /** Le statut HTTP, ou 0 quand aucune reponse n'est parvenue. */
  readonly status: number;
  /** Le code namespace de BACK-09, ou un code `api_client.*` a defaut. */
  readonly code: string;
  readonly details: Record<string, unknown> | null;
  /** L'identifiant de correlation (BACK-11), a citer dans un rapport d'incident. */
  readonly requestId: string | null;
  /** Le corps tel qu'il est arrive, quand il n'etait pas au format attendu. */
  readonly rawBody: unknown;

  constructor(init: {
    status: number;
    code: string;
    message: string;
    details: Record<string, unknown> | null;
    requestId: string | null;
    rawBody?: unknown;
    cause?: unknown;
  }) {
    super(init.message, { cause: init.cause });
    this.name = 'ApiError';
    this.status = init.status;
    this.code = init.code;
    this.details = init.details;
    this.requestId = init.requestId;
    this.rawBody = init.rawBody;
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError;
}

/**
 * Reconnait le format de BACK-09.
 *
 * TOLERANT A DESSEIN : seuls `code` et `message` sont exiges. Un `details` d'un
 * type inattendu ne doit pas faire perdre le message, qui est la seule chose que
 * l'utilisateur lira.
 */
function isErrorBody(value: unknown): value is Partial<ApiErrorBody> & {
  code: string;
  message: string;
} {
  if (typeof value !== 'object' || value === null) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return typeof candidate.code === 'string' && typeof candidate.message === 'string';
}

/** Ramene une reponse en echec a une `ApiError`, formatee ou non. */
export function normalizeErrorResponse(input: {
  status: number;
  requestId: string | null;
  payload: unknown;
}): ApiError {
  if (isErrorBody(input.payload)) {
    const details = input.payload.details;
    const bodyRequestId = input.payload.request_id;

    return new ApiError({
      status: input.status,
      code: input.payload.code,
      message: input.payload.message,
      // `details` est toujours un OBJET cote backend, jamais une liste -- BACK-09
      // le motive nommement pour que le client le type proprement. On refuse
      // donc tout le reste plutot que d'elargir le type a ce qui n'arrivera pas.
      details:
        typeof details === 'object' && details !== null && !Array.isArray(details) ? details : null,
      // L'EN-TETE FAIT FOI, le corps sert de repli : l'intergiciel de
      // correlation pose X-Request-ID sur toute reponse, y compris celles qui
      // n'ont pas de corps d'erreur.
      requestId: input.requestId ?? (typeof bodyRequestId === 'string' ? bodyRequestId : null),
      rawBody: input.payload,
    });
  }

  return new ApiError({
    status: input.status,
    code: CLIENT_ERROR_CODES.malformed,
    message: `L'API a repondu ${String(input.status)} hors du format d'erreur attendu.`,
    details: null,
    requestId: input.requestId,
    rawBody: input.payload,
  });
}

/**
 * Ramene un echec de transport a une `ApiError`.
 *
 * `status: 0` ET NON 500 : aucune reponse n'est parvenue, il n'y a pas de statut
 * a rapporter. Un `if (error.status === 401)` de FRONT-07 ne doit jamais
 * confondre « l'API a refuse » et « l'API n'a pas repondu ».
 */
export function transportFailure(cause: unknown): ApiError {
  return new ApiError({
    status: 0,
    code: CLIENT_ERROR_CODES.unreachable,
    message: "L'API n'a pas repondu. Verifier la connexion, puis reessayer.",
    details: null,
    requestId: null,
    cause,
  });
}
