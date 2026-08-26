/**
 * SHARED-03 -- FICHIER GENERE PAR ORVAL. NE PAS EDITER.
 * Source : packages/api-client/openapi.json, exporte depuis l'API FastAPI.
 * Regeneration :  make generate-api
 * Sortie versionnee (ADR-0007) : un diff ici est un changement de contrat.
 */
import * as zod from 'zod';


/**
 * Repond immediatement, sans toucher a aucune dependance externe.
 *
 * Returns:
 *     Le rapport de vie -- toujours le meme : si cette fonction s'execute,
 *     le processus est vivant.
 * @summary Sonde de vie
 */
export const checkLivenessResponseStatusDefault = `alive`;

export const CheckLivenessResponse = zod.object({
  "status": zod.literal("alive").default(checkLivenessResponseStatusDefault).meta({ title: 'Status' })
}).describe('Reponse de la sonde de vie : le processus repond, rien de plus.')

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
export const CheckReadinessResponse = zod.object({
  "components": zod.object({
  "postgres": zod.enum(['ok', 'unreachable']),
  "redis": zod.enum(['ok', 'unreachable'])
}).describe('Etat de chaque dependance interrogee par la sonde de disponibilite.'),
  "status": zod.enum(['ready', 'unready'])
}).describe('Reponse de la sonde de disponibilite, composant par composant.')

