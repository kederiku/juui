'use client';

import { getCheckReadinessQueryKey, useCheckReadiness } from '@repo/api-client/api/health';
import { publicQueryKey } from '@repo/api-client/query-keys';
import { Badge } from '@repo/ui/components/badge';

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
 * TROIS ETATS, ET RIEN DE PLUS. Le squelette de chargement appartient a
 * FRONT-18a, le rendu des erreurs a FRONT-10 : ce qui est ici est le minimum
 * qui rende le cablage VISIBLE, et il disparaitra avec le premier ecran metier.
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
  const { data, isPending, isError, fetchStatus } = useCheckReadiness({
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
    return <Badge variant="destructive">Service injoignable</Badge>;
  }

  return (
    <Badge variant={data.status === 'ready' ? 'default' : 'destructive'}>
      {data.status === 'ready' ? 'Service prêt' : 'Service dégradé'}
    </Badge>
  );
}
