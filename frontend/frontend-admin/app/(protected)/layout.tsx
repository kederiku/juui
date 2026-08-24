import { Separator } from '@repo/ui/components/separator';
import { SidebarInset, SidebarProvider, SidebarTrigger } from '@repo/ui/components/sidebar';
import { ThemeToggle } from '@repo/ui/components/theme-toggle';
import { TooltipProvider } from '@repo/ui/components/tooltip';

import { AdminBreadcrumb } from '@/components/admin-breadcrumb';
import { AdminSidebar } from '@/components/admin-sidebar';
import { requireRole } from '@/lib/require-role';

import type { ReactNode } from 'react';

/**
 * Le shell du back-office (FRONT-03) : navigation laterale, fil d'Ariane, zone
 * de contenu. Toutes les pages authentifiees passent par ici.
 *
 * C'est aussi la frontiere de l'application : le groupe `(protected)` n'ajoute
 * rien a l'URL -- les parentheses le rendent invisible au routeur -- mais tout
 * ce qu'il contient est garde par le `requireRole` ci-dessous, et rendu par
 * requete.
 */

/**
 * PAS DE RENDU STATIQUE, ce que reclame le ticket pour une application privee.
 *
 * La ligne est presque redondante -- `requireRole` lit un cookie, ce qui suffit
 * deja a rendre le segment dynamique -- et elle est ecrite quand meme, ici et
 * nulle part ailleurs. C'est la seule directive de ce genre du depot : le README
 * de FRONT-02 pose qu'elle tire sa valeur de sa rarete. Elle dit qu'aucune page
 * de back-office ne doit finir en HTML prerendu, meme le jour ou l'une d'elles
 * n'aura besoin d'aucune donnee de session pour s'afficher.
 *
 * Elle ne s'applique pas a la page de connexion, qui vit hors de ce groupe : ce
 * qu'elle affiche n'a rien de confidentiel.
 */
export const dynamic = 'force-dynamic';

export default async function ProtectedLayout({ children }: { children: ReactNode }) {
  // Garde de role. Sans session ou sans le bon role, la fonction ne rend pas la
  // main : elle redirige. Ce qui suit n'est donc atteint que par un
  // administrateur -- au sens ou le back-office peut l'entendre aujourd'hui.
  const session = await requireRole('admin');

  return (
    /*
     * `TooltipProvider` est monte ici et non dans `@repo/ui` : les info-bulles
     * de la barre laterale repliee en dependent, et ce fournisseur n'a de sens
     * que la ou des info-bulles existent -- l'imposer au ThemeProvider partage
     * le ferait porter aux deux autres applications sans raison.
     */
    <TooltipProvider>
      <SidebarProvider>
        <AdminSidebar role={session.role} />

        <SidebarInset>
          <header className="flex h-16 shrink-0 items-center gap-2 border-b px-4">
            <SidebarTrigger className="-ml-1" />
            <Separator orientation="vertical" className="mr-1 !h-4" />
            <AdminBreadcrumb />
            <div className="ml-auto">
              <ThemeToggle />
            </div>
          </header>

          <main className="flex flex-1 flex-col gap-6 p-6">{children}</main>
        </SidebarInset>
      </SidebarProvider>
    </TooltipProvider>
  );
}
