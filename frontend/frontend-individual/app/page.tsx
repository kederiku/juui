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

/**
 * Page d'accueil de frontend-individual (FRONT-02).
 *
 * Volontairement sans contenu metier, comme celle de frontend-professional :
 * elle n'existe que pour rendre VISIBLE le cablage du monorepo, et ici en plus
 * celui du volet SEO. Chaque element atteste un maillon precis, et sa
 * disparition designerait la piece cassee. Les premiers ecrans reels --
 * annuaire des cliniques, prise de rendez-vous, carnet de sante -- la
 * remplaceront.
 *
 * Aucune API dynamique n'est appelee : Next la prerend donc au BUILD, ce que
 * `next build` confirme en la marquant statique. C'est la generation statique
 * que demande le ticket, obtenue sans rien forcer.
 */
export default function HomePage() {
  return (
    <main className="mx-auto flex min-h-svh max-w-2xl flex-col gap-8 px-6 py-16">
      <header className="flex items-start justify-between gap-4">
        <div className="space-y-2">
          <Badge variant="secondary">Espace particuliers</Badge>
          <h1 className="text-3xl font-semibold tracking-tight">Juui</h1>
          <p className="text-muted-foreground">
            Rendez-vous en ligne et carnet de santé numérique pour vos animaux.
          </p>
        </div>
        <ThemeToggle />
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
              depuis sa source TypeScript — la bascule ci-dessus comprise, remontée dans le package
              partagé plutôt que recopiée depuis l’application professionnelle.
            </li>
            <li>
              Ils sont stylés : les classes de la bibliothèque ont survécu à la purge, donc la
              directive <code className="font-mono">@source</code> du thème partagé fait son
              travail.
            </li>
            <li>
              La bascule repeint la page, donc le fournisseur de thème et sa classe{' '}
              <code className="font-mono">.dark</code> répondent.
            </li>
            <li>
              Ce texte est rendu en Geist, donc <code className="font-mono">--font-juui-sans</code>{' '}
              alimente bien le <code className="font-mono">--font-sans</code> du thème.
            </li>
          </ul>
          <Button>Rien à faire pour l’instant</Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Ce qui distingue cette application</CardTitle>
          <CardDescription>
            Seule des trois à être publique, donc la seule à être indexée.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="list-disc space-y-2 pl-5 text-sm text-muted-foreground">
            <li>
              <a className="underline underline-offset-4" href="/robots.txt">
                /robots.txt
              </a>{' '}
              autorise l’indexation et annonce le sitemap.
            </li>
            <li>
              <a className="underline underline-offset-4" href="/sitemap.xml">
                /sitemap.xml
              </a>{' '}
              liste les pages publiques — l’accueil pour l’instant.
            </li>
            <li>
              Les deux fichiers, comme cette page, sont générés au build : le code source de la page
              contient déjà son titre, sa description et ses balises Open Graph.
            </li>
          </ul>
        </CardContent>
      </Card>
    </main>
  );
}
