import { QueryProvider } from '@repo/api-client/query-provider';
import { ThemeProvider } from '@repo/ui/components/theme-provider';
import { Geist, Geist_Mono } from 'next/font/google';

import './globals.css';

import type { Metadata } from 'next';
import type { ReactNode } from 'react';

/**
 * Layout racine de frontend-admin (FRONT-03).
 *
 * Meme squelette que celui des deux autres applications -- police, theme,
 * metadonnees -- avec un bloc de metadonnees reduit a l'essentiel : ce
 * back-office n'est lu par aucun robot, et le seul reglage qui compte ici est
 * celui qui le leur dit.
 *
 * Le shell du back-office -- navigation laterale, fil d'Ariane, zone de contenu
 * -- n'est PAS ici mais dans `app/(protected)/layout.tsx` : la page de connexion
 * partage la police et le theme, pas la navigation d'un espace ou l'on n'est pas
 * encore entre.
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
    default: 'Juui Admin',
    template: '%s · Juui Admin',
  },
  description: 'Back-office de la plateforme Juui.',

  /*
   * L'EXACT INVERSE du bloc de frontend-individual, au meme endroit et dans le
   * meme ordre : la comparaison des deux fichiers doit suffire a voir laquelle
   * des applications est publique. Celle-ci ne l'est pas.
   *
   * `nocache` et `noarchive` s'ajoutent au refus d'indexation : ils interdisent
   * a un moteur de CONSERVER une copie d'une page qu'il aurait vue -- une page
   * de back-office en cache public survivrait a sa depublication.
   *
   * Ces balises ne protegent rien : elles s'adressent aux robots qui les
   * respectent. Ce qui protege, c'est `middleware.ts` et, en dernier ressort,
   * l'API. Elles evitent l'accident, pas l'attaque.
   */
  robots: {
    index: false,
    follow: false,
    nocache: true,
    googleBot: {
      index: false,
      follow: false,
      noarchive: true,
      'max-snippet': 0,
      'max-image-preview': 'none',
      'max-video-preview': 0,
    },
  },
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
