import { Badge } from '@repo/ui/components/badge';
import { Button } from '@repo/ui/components/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@repo/ui/components/card';
import { ThemeToggle } from '@repo/ui/components/theme-toggle';

import { ServiceStatus } from '@/components/service-status';

/**
 * Page d'accueil de frontend-professional (FRONT-01).
 *
 * Volontairement sans contenu metier : elle n'existe que pour rendre VISIBLE le
 * cablage du monorepo. Chaque element ci-dessous atteste un maillon precis, et
 * sa disparition designerait la piece cassee. Les premiers ecrans reels la
 * remplaceront.
 */
export default function HomePage() {
  return (
    <main className="mx-auto flex min-h-svh max-w-2xl flex-col gap-8 px-6 py-16">
      <header className="flex items-start justify-between gap-4">
        <div className="space-y-2">
          <Badge variant="secondary">Espace professionnel</Badge>
          <h1 className="text-3xl font-semibold tracking-tight">Juui Pro</h1>
          <p className="text-muted-foreground">
            Agenda et gestion du cabinet pour les cliniques vétérinaires.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <ServiceStatus />
          <ThemeToggle />
        </div>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>Câblage du monorepo</CardTitle>
          <CardDescription>
            Cette page n’a pas d’autre objet que de prouver que chaque maillon tient.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <ul className="list-disc space-y-2 pl-5 text-sm text-muted-foreground">
            <li>
              Ces composants viennent de <code className="font-mono">@repo/ui</code>, transpilé
              depuis sa source TypeScript.
            </li>
            <li>
              Ils sont stylés : les classes de la bibliothèque ont survécu à la purge, donc la
              directive <code className="font-mono">@source</code> du thème partagé fait son
              travail.
            </li>
            <li>
              La bascule ci-dessus repeint la page, donc le fournisseur de thème et sa classe{' '}
              <code className="font-mono">.dark</code> répondent.
            </li>
            <li>
              Ce texte est rendu en Geist, donc <code className="font-mono">--font-juui-sans</code>{' '}
              alimente bien le <code className="font-mono">--font-sans</code> du thème.
            </li>
            <li>
              Le badge d’état en haut à droite vient de l’API, appelé par un hook généré : le
              fournisseur de données est donc bien au-dessus de lui, en un seul exemplaire. Le cache
              vit en mémoire, le temps de la page : un retour de navigation ressert la réponse
              pendant 60 s, un rechargement complet repart au réseau.
            </li>
          </ul>
          <Button>Rien à faire pour l’instant</Button>
        </CardContent>
      </Card>
    </main>
  );
}
