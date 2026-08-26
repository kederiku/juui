/**
 * SHARED-03 -- FICHIER GENERE PAR ORVAL. NE PAS EDITER.
 * Source : packages/api-client/openapi.json, exporte depuis l'API FastAPI.
 * Regeneration :  make generate-api
 * Sortie versionnee (ADR-0007) : un diff ici est un changement de contrat.
 */
import type { ReadinessComponentsPostgres } from './readiness-components-postgres';
import type { ReadinessComponentsRedis } from './readiness-components-redis';

/**
 * Etat de chaque dependance interrogee par la sonde de disponibilite.
 */
export interface ReadinessComponents {
  postgres: ReadinessComponentsPostgres;
  redis: ReadinessComponentsRedis;
}
