import { Badge } from '@repo/ui/components/badge';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@repo/ui/components/card';

/**
 * Tableau de bord du back-office (FRONT-03).
 *
 * Volontairement sans contenu metier, comme les pages d'accueil des deux autres
 * applications : elle n'existe que pour rendre VISIBLE ce que le ticket demande
 * de mettre en place. Chaque element atteste un maillon precis, et sa
 * disparition designerait la piece cassee. Les premiers ecrans reels --
 * validation des cliniques, gestion des comptes, journal d'activite -- la
 * remplaceront.
 */
export default function DashboardPage() {
  return (
    <>
      <header className="space-y-2">
        <Badge variant="secondary">Administration</Badge>
        <h1 className="text-2xl font-semibold tracking-tight">Tableau de bord</h1>
        <p className="text-muted-foreground">Back-office de la plateforme Juui.</p>
      </header>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Câblage du monorepo</CardTitle>
            <CardDescription>
              Cette page n’a pas d’autre objet que de prouver que chaque maillon tient.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="list-disc space-y-2 pl-5 text-sm text-muted-foreground">
              <li>
                La barre latérale, le fil d’Ariane et la bascule de thème viennent tous de{' '}
                <code className="font-mono">@repo/ui</code>, transpilé depuis sa source TypeScript.
              </li>
              <li>
                Ils sont stylés : les classes de la bibliothèque ont survécu à la purge, et les
                variables <code className="font-mono">--sidebar-*</code> du thème partagé peignent
                la navigation.
              </li>
              <li>
                Ce texte est rendu en Geist, donc{' '}
                <code className="font-mono">--font-juui-sans</code> alimente bien le{' '}
                <code className="font-mono">--font-sans</code> du thème.
              </li>
            </ul>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Ce qui distingue cette application</CardTitle>
            <CardDescription>
              Seule des trois à être entièrement privée, donc la seule à se fermer par défaut.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="list-disc space-y-2 pl-5 text-sm text-muted-foreground">
              <li>
                Toute adresse hors <code className="font-mono">/login</code> redirige vers la
                connexion tant qu’aucune session n’est présente.
              </li>
              <li>
                <a className="underline underline-offset-4" href="/robots.txt">
                  /robots.txt
                </a>{' '}
                interdit l’indexation entière, et les métadonnées de la page portent{' '}
                <code className="font-mono">noindex</code>.
              </li>
              <li>
                Rien n’est prérendu ici : ce segment est rendu à la requête, session lue à chaque
                fois.
              </li>
            </ul>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
