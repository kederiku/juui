/**
 * SHARED-03 -- FICHIER GENERE PAR ORVAL. NE PAS EDITER.
 * Source : packages/api-client/openapi.json, exporte depuis l'API FastAPI.
 * Regeneration :  make generate-api
 * Sortie versionnee (ADR-0007) : un diff ici est un changement de contrat.
 */
import type { ErrorResponseDetails } from './error-response-details';

/**
 * Corps de toute reponse d'erreur : { code, message, details, request_id }.
 *
 * Serialise avec ses quatre cles TOUJOURS presentes -- les handlers passent
 * par `model_dump(mode="json")` sans `exclude_none`, et c'est voulu : un
 * contrat dont les cles apparaissent et disparaissent n'est pas un contrat.
 */
export interface ErrorResponse {
  code: string;
  details?: ErrorResponseDetails;
  message: string;
  request_id?: string | null;
}
