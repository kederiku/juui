'use client';

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from '@repo/ui/components/sidebar';
import { PawPrintIcon } from 'lucide-react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';

import { navigationForRole } from '@/components/navigation';
import { ROLE_LABELS } from '@/lib/session';

import type { Role } from '@/lib/session';

/**
 * Navigation laterale du back-office (FRONT-03).
 *
 * Composee ici, a partir des primitives `Sidebar*` de `@repo/ui` : ce sont
 * elles qui sont partagees -- frontend-professional aura sa propre navigation --
 * pas cet assemblage-ci, qui ne parle que des sections de l'administration.
 *
 * Composant CLIENT, pour deux raisons qui tiennent toutes deux a l'interaction :
 * `usePathname` designe l'entree active, et le repli de la barre est un etat de
 * navigateur (Ctrl/Cmd+B, ou la poignee laterale).
 *
 * Le role vient du serveur en prop plutot que d'un contexte : il est deja lu par
 * la garde de `(protected)/layout.tsx`, et le redemander cote client ferait deux
 * sources pour une meme reponse.
 */
export function AdminSidebar({ role }: { role: Role }) {
  const pathname = usePathname();
  const entries = navigationForRole(role);

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" asChild>
              <Link href="/">
                {/*
                 * La marque tient dans un carre de la taille exacte du bouton
                 * replie. Sans ce carre, le libelle deborderait de quelques
                 * pixels et laisserait un « J » tronque a cote de l'icone.
                 */}
                <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground">
                  <PawPrintIcon />
                </div>
                <span className="truncate font-semibold">Juui Admin</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Plateforme</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {entries.map((entry) => {
                /*
                 * L'accueil ne peut pas se comparer par prefixe : « / » prefixe
                 * toutes les adresses de l'application, et le tableau de bord
                 * resterait actif sur chacune d'elles.
                 */
                const isActive =
                  entry.href === '/' ? pathname === '/' : pathname.startsWith(entry.href);

                return (
                  <SidebarMenuItem key={entry.href}>
                    {/* `tooltip` n'apparait qu'une fois la barre repliee, ou le libelle est masque. */}
                    <SidebarMenuButton asChild isActive={isActive} tooltip={entry.label}>
                      <Link href={entry.href}>
                        <entry.icon />
                        <span>{entry.label}</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter>
        <p className="px-2 text-xs text-muted-foreground group-data-[collapsible=icon]:hidden">
          Connecté en tant que{' '}
          <span className="font-medium text-foreground">{ROLE_LABELS[role]}</span>
        </p>
      </SidebarFooter>

      {/* Poignee de redimensionnement : c'est elle qui replie la barre a la souris. */}
      <SidebarRail />
    </Sidebar>
  );
}
