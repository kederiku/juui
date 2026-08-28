'use client';

import { getCheckReadinessQueryKey, useCheckReadiness } from '@repo/api-client/api/health';
import { resolveApiError } from '@repo/api-client/errors/messages';
import { publicQueryKey } from '@repo/api-client/query-keys';
import { Badge } from '@repo/ui/components/badge';
import { ErrorState } from '@repo/ui/components/error/error-state';
import { RequestId } from '@repo/ui/components/error/request-id';

/**
 * FRONT-04 -- La preuve, a l'ecran, que le QueryProvider est REELLEMENT au-dessus
 * des hooks generes.
 *
 * POURQUOI UN ECRAN, ALORS QUE TOUT LE RESTE SE PROUVE DANS NODE
 * La panne que nomme l'ecart SHARED-03 -- deux exemplaires de
 * `@tanstack/react-query`, donc deux contextes React, donc un fournisseur
 * invisible aux hooks -- ne produit AUCUNE erreur de compilation, et
 * `make verify-api-client` ne rend aucun hook. Elle ne se voit qu'a
 * l'execution : un fournisseur monte au-dessus de rien n'aurait rien prouve.
 *
 * IL PASSE PAR LA FABRIQUE DE CLEFS, ET C'EST L'EXEMPLE A COPIER. La clef
 * d'Orval identifie une ROUTE ; c'est la portee qui dit a QUI la reponse
 * appartient. Une sonde de sante est publique -- aucun groupe, et il faut que ce
 * soit ECRIT plutot que deduit d'une absence. Un ecran de tenance ecrirait
 * `groupQueryKey(scope, ...)`, que le typage refuse de composer sans groupe.
 *
 * QUATRE ETATS. Le squelette de chargement appartient toujours a FRONT-18a ;
 * le rendu des erreurs, lui, est arrive avec FRONT-10 et c'est ICI qu'il se
 * voit : sans consommateur, rien ne prouverait que la chaine code -> message ->
 * ecran tient. Ce composant disparaitra avec le premier ecran metier.
 *
 * POUR LE VOIR : `make dev`, puis `docker compose stop redis`. La sonde repond
 * alors 503 PAR LA ROUTE NORMALE -- donc en traversant tous les intergiciels,
 * donc avec `X-Request-ID` expose --, et le bloc complet s'affiche, identifiant
 * copiable compris. Arreter l'API entiere ne le montrerait PAS : la requete
 * echouerait au transport, sans reponse, donc sans identifiant.
 *
 * CE QUE CETTE DEMONSTRATION NE PROUVE PAS : la table par module. Le corps de ce
 * 503 est un `ReadinessReport` et non une erreur BACK-09 -- la sonde repond la
 * meme forme en panne et en sante --, si bien que le mutator pose son propre
 * code plutot que d'en lire un. Les entrees metier attendent BACK-28 ; les
 * sondes hors ligne les couvrent d'ici la.
 *
 * A SAVOIR : un service degrade repond 503, que le mutator normalise en
 * ApiError -- il arrive donc par `isError`, jamais par `data`. Le cas
 * `status !== 'ready'` reste ecrit parce que le contrat l'autorise (BACK-08).
 *
 * DANS `features/health/` DEPUIS FRONT-09. Le nom de la feature est celui du
 * dossier qu'Orval produit en `tags-split` et que ce composant consomme --
 * `@repo/api-client/api/health`. C'est la seule correspondance qui existe
 * aujourd'hui, et elle vaut demonstration : la frontiere metier devient visible
 * des deux cotes. `health` est une etiquette OpenAPI et non un module backend,
 * ce qui est consigne au registre des ecarts.
 */
export function ServiceStatus() {
  const { data, isPending, isError, error, fetchStatus } = useCheckReadiness({
    query: { queryKey: publicQueryKey(getCheckReadinessQueryKey()) },
  });

  // `isPending` NE VEUT PAS DIRE « EN COURS DE CHARGEMENT », et la nuance se
  // paie ici. `networkMode` reste au defaut `'online'` : navigateur hors ligne,
  // TanStack met la requete en pause en la LAISSANT `pending`. Un composant dont
  // le seul metier est de dire si le service repond afficherait « Verification »
  // indefiniment. `fetchStatus` est ce qui distingue les deux.
  if (fetchStatus === 'paused') {
    return <Badge variant="destructive">Hors ligne</Badge>;
  }

  if (isPending) {
    return <Badge variant="secondary">Vérification…</Badge>;
  }

  if (isError) {
    // `error` est type `ErrorType<...>`, c'est-a-dire l'`ApiError` que le
    // mutator leve reellement (FRONT-10). Avant, le code genere le typait
    // d'apres les reponses declarees dans l'OpenAPI -- ici `ReadinessReport`,
    // qui n'arrive jamais par ce chemin.
    const resolved = resolveApiError(error);
    return (
      <ErrorState className="max-w-xs" title="Service injoignable" message={resolved.message}>
        {resolved.visibleRequestId === null ? null : (
          <RequestId requestId={resolved.visibleRequestId} />
        )}
      </ErrorState>
    );
  }

  return (
    <Badge variant={data.status === 'ready' ? 'default' : 'destructive'}>
      {data.status === 'ready' ? 'Service prêt' : 'Service dégradé'}
    </Badge>
  );
}
