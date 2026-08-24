import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@repo/ui/components/card';

import { getSession } from '@/lib/require-role';

import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Utilisateurs',
};

/**
 * Comptes de la plateforme (FRONT-03).
 *
 * Page d'attente : la gestion des comptes suppose l'API et le client genere
 * (SHARED-03), qui n'existent pas. Elle sert ici a deux choses -- donner une
 * deuxieme section a la navigation, et rendre VISIBLE le role lu par la garde de
 * `(protected)/layout.tsx`, qui resterait sinon une intention sans preuve.
 */
export default async function UtilisateursPage() {
  const session = await getSession();

  return (
    <>
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">Utilisateurs</h1>
        <p className="text-muted-foreground">Comptes professionnels, particuliers et internes.</p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>Contrôle d’accès par rôle</CardTitle>
          <CardDescription>
            Un confort d’affichage, et rien de plus : la vérification qui fait foi est celle du
            backend.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4 text-sm text-muted-foreground">
          <p>
            Rôle de la session courante :{' '}
            <span className="font-medium text-foreground">{session?.role ?? 'aucun'}</span>. C’est
            lui que lit la garde du groupe <code className="font-mono">(protected)</code>, et lui
            qui filtre les entrées de la navigation latérale.
          </p>
          <p>
            Il n’est pour l’instant pas vérifié : le jeton n’est pas décodé, sa présence suffit. La
            signature, l’expiration et le rafraîchissement arrivent avec FRONT-07 ; côté serveur,
            c’est <code className="font-mono">require_role</code> (BACK-10) qui refusera la requête,
            quoi qu’affiche cet écran.
          </p>
        </CardContent>
      </Card>
    </>
  );
}
