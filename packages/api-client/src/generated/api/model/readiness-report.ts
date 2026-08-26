/**
 * SHARED-03 -- FICHIER GENERE PAR ORVAL. NE PAS EDITER.
 * Source : packages/api-client/openapi.json, exporte depuis l'API FastAPI.
 * Regeneration :  make generate-api
 * Sortie versionnee (ADR-0007) : un diff ici est un changement de contrat.
 */
import type { ReadinessComponents } from './readiness-components';
import type { ReadinessReportStatus } from './readiness-report-status';

/**
 * Reponse de la sonde de disponibilite, composant par composant.
 */
export interface ReadinessReport {
  components: ReadinessComponents;
  status: ReadinessReportStatus;
}
