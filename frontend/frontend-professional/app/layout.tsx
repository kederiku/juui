import { ThemeProvider } from '@repo/ui/components/theme-provider';
import { Geist, Geist_Mono } from 'next/font/google';

import './globals.css';

import type { Metadata } from 'next';
import type { ReactNode } from 'react';

/**
 * Layout racine de frontend-professional (FRONT-01).
 *
 * Trois responsabilites, et rien d'autre : charger la police, poser le theme,
 * declarer les metadonnees. Les fournisseurs de donnees viendront s'y ajouter en
 * FRONT-04.
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
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  );
}
