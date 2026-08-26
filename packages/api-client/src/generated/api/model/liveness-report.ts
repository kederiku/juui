/**
 * SHARED-03 -- FICHIER GENERE PAR ORVAL. NE PAS EDITER.
 * Source : packages/api-client/openapi.json, exporte depuis l'API FastAPI.
 * Regeneration :  make generate-api
 * Sortie versionnee (ADR-0007) : un diff ici est un changement de contrat.
 */

/**
 * Reponse de la sonde de vie : le processus repond, rien de plus.
 */
export const LivenessReportValue = {
  status: 'alive',
} as const;
export type LivenessReport = typeof LivenessReportValue;
