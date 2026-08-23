import { Badge } from '@repo/ui/components/badge';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@repo/ui/components/card';
import { ThemeToggle } from '@repo/ui/components/theme-toggle';

import { SESSION_COOKIE_NAME } from '@/lib/session';

import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Connexion',
};

/**
 * Page de connexion du back-office (FRONT-03).
 *
 * LA SEULE PAGE PUBLIQUE de l'application : le `matcher` de `middleware.ts`
 * l'exclut, tout le reste y passe. C'est ici que retombe quiconque n'a pas de
 * session -- donc, tant que rien n'en emet, tout le monde.
 *
 * ELLE N'A PAS DE FORMULAIRE, et c'est delibere. Le flux d'authentification est
 * l'objet de FRONT-07, qui possede ce fichier au titre de son perimetre
 * `frontend/<app>/app/(auth)/login/page.tsx` -- le chemin est donc le sien, au
 * caractere pres, pour qu'il ait a remplacer cette page plutot qu'a en creer une
 * autre a cote. Ecrire ici un formulaire sans API derriere aurait produit du
 * code a jeter, et un ecran qui ment sur ce qu'il sait faire.
 *
 * Elle ne porte AUCUN `dynamic`, contrairement au groupe `(protected)` : rien de
 * confidentiel ne s'y affiche. Next la rend malgre tout par requete, parce
 * qu'elle lit `searchParams` -- c'est le framework qui en decide, non ce
 * fichier, et la difference se verra le jour ou ce parametre disparaitra.
 */
export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string }>;
}) {
  const { next } = await searchParams;

  return (
    <main className="mx-auto flex min-h-svh max-w-lg flex-col justify-center gap-6 px-6 py-16">
      <header className="flex items-start justify-between gap-4">
        <div className="space-y-2">
          <Badge variant="secondary">Administration</Badge>
          <h1 className="text-3xl font-semibold tracking-tight">Juui Admin</h1>
        </div>
        <ThemeToggle />
      </header>

      <Card>
        <CardHeader>
          <CardTitle>Connexion requise</CardTitle>
          <CardDescription>
            Ce back-office est réservé aux administrateurs de la plateforme.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4 text-sm text-muted-foreground">
          <p>
            Le formulaire de connexion arrive avec le flux d’authentification (FRONT-07) : jeton en
            cookie <code className="font-mono">httpOnly</code>, rafraîchissement transparent et
            déconnexion. Cette page en tient la place, et son adresse est déjà la bonne.
          </p>
          <p>
            En attendant, poser le cookie <code className="font-mono">{SESSION_COOKIE_NAME}</code>{' '}
            sur ce domaine ouvre le back-office — la marche à suivre est dans le README.
          </p>
          {next ? (
            <p>
              Après connexion, retour à <code className="font-mono">{next}</code>.
            </p>
          ) : null}
        </CardContent>
      </Card>
    </main>
  );
}
