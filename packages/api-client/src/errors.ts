/**
 * SHARED-03 -- Les erreurs de l'API, telles que le navigateur les voit.
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
 * POURQUOI LE TYPE DU CORPS EST ECRIT ICI ET NON IMPORTE DU GENERE
 * `ErrorResponse` est declare cote backend sur le routeur v1, mais AUCUNE route
 * v1 n'existe encore : le composant n'apparait donc pas dans l'OpenAPI
 * d'aujourd'hui, et Orval n'en genere aucun type. A remplacer par un
 * `import type { ErrorResponse } from './generated/api/model/error-response'`
 * des la premiere route metier (BACK-28) -- un import de TYPE, sans couplage a
 * l'execution.
 */

/** Le corps d'erreur promis par BACK-09, quatre clefs toujours presentes. */
export type ApiErrorBody = {
  code: string;
  message: string;
  details: Record<string, unknown> | null;
  request_id: string | null;
};

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
} as const;

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
