import { QueryProvider } from '@repo/api-client/query-provider';
import { ThemeProvider } from '@repo/ui/components/theme-provider';
import { Geist, Geist_Mono } from 'next/font/google';

import './globals.css';

import type { Metadata } from 'next';
import type { ReactNode } from 'react';

/**
 * Layout racine de frontend-professional (FRONT-01).
 *
 * Quatre responsabilites, et rien d'autre : charger la police, poser le theme,
 * monter le fournisseur de donnees (FRONT-04), declarer les metadonnees. Les
 * trois applications montent le MEME `QueryProvider`, celui de
 * `@repo/api-client` : un seul exemplaire de TanStack Query, donc un seul
 * contexte React -- deux copies rendraient le fournisseur invisible aux hooks
 * generes, sans la moindre erreur de compilation.
 */

/*
 * Geist, la police variable dessinee pour Next. `next/font` la telecharge a la
 * COMPILATION et la sert depuis notre propre domaine : aucune requete vers
 * Google a l'execution, et pas de decalage de mise en page au chargement.
 *
 * Le nom des variables n'est pas libre : `--font-juui-sans` et
 * `--font-juui-mono` sont le contrat qu'attend le theme partage, dont le
 * `--font-sans` vaut `var(--font-juui-sans, ...)`. Les nommer autrement
 * laisserait silencieusement la valeur de repli s'appliquer.
 */
const geistSans = Geist({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-juui-sans',
});

const geistMono = Geist_Mono({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-juui-mono',
});

export const metadata: Metadata = {
  title: {
    default: 'Juui Pro',
    template: '%s · Juui Pro',
  },
  description: 'Agenda et gestion du cabinet pour les cliniques vétérinaires.',
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    /*
     * `suppressHydrationWarning` n'est pas negociable : next-themes ecrit la
     * classe `.dark` sur <html> avant l'hydratation, pour eviter le flash de
     * theme clair. Le rendu serveur ne peut pas la prevoir, et React signalerait
     * l'ecart a chaque page sans cet attribut.
     */
    <html
      lang="fr"
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable}`}
    >
      {/*
       * `font-sans` est applique ici et non par le theme : le preset partage se
       * borne a definir le token, il ne l'impose a aucun element. Sans cette
       * classe, la page s'afficherait dans la police par defaut du navigateur.
       */}
      <body className="font-sans antialiased">
        {/*
         * L'ORDRE N'EST PAS ARBITRAIRE, MAIS IL EST SANS EFFET : next-themes
         * ecrit sur <html> et ne consomme rien du cache, TanStack Query ignore
         * le theme. Le theme reste dessus parce que c'est lui qui etait la, et
         * que le diff des trois applications se lit ainsi en deux lignes.
         *
         * PAS DE app/providers.tsx : `QueryProvider` porte deja `'use client'`,
         * ce layout reste donc un composant serveur (FRONT-04).
         */}
        <ThemeProvider>
          <QueryProvider>{children}</QueryProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
