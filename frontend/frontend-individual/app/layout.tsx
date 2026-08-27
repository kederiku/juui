import { QueryProvider } from '@repo/api-client/query-provider';
import { ThemeProvider } from '@repo/ui/components/theme-provider';
import { Geist, Geist_Mono } from 'next/font/google';

import './globals.css';

import { SITE_URL } from '@/lib/site-url';

import type { Metadata } from 'next';
import type { ReactNode } from 'react';

/**
 * Layout racine de frontend-individual (FRONT-02).
 *
 * Meme squelette que celui de frontend-professional -- police, theme,
 * metadonnees -- avec un bloc de metadonnees nettement plus fourni : c'est la
 * seule des trois applications qui soit publique, donc la seule dont les
 * balises de tete soient lues par autre chose qu'un navigateur.
 */

/*
 * Geist, la police variable dessinee pour Next. `next/font` la telecharge a la
 * COMPILATION et la sert depuis notre propre domaine : aucune requete vers
 * Google a l'execution, et pas de decalage de mise en page au chargement -- ce
 * dernier point compte double ici, le decalage cumule etant l'une des trois
 * mesures Core Web Vitals que les moteurs prennent en compte.
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

/*
 * Titre et description sont ecrits une fois et repris par les trois canaux --
 * balises de tete, Open Graph, carte Twitter. Les recopier laisserait deux
 * d'entre eux vieillir sans que rien ne le signale.
 */
const SITE_NAME = 'Juui';
const SITE_TITLE = 'Juui — Prenez rendez-vous chez votre vétérinaire';
const SITE_DESCRIPTION =
  'Trouvez une clinique vétérinaire, prenez rendez-vous en ligne et retrouvez le carnet de santé numérique de vos animaux, au même endroit.';

export const metadata: Metadata = {
  /*
   * Base de resolution des URLs relatives de ce bloc. Sans elle, Next avertit a
   * chaque build et retombe sur une adresse devinee : les `og:url` et les
   * balises canoniques pointeraient alors ailleurs qu'en production.
   */
  metadataBase: new URL(SITE_URL),

  title: {
    default: SITE_TITLE,
    template: `%s · ${SITE_NAME}`,
  },
  description: SITE_DESCRIPTION,
  applicationName: SITE_NAME,

  /*
   * Canonique de l'accueil. Un site public finit toujours par etre atteint par
   * plusieurs adresses -- parametres de campagne, barre oblique finale, variante
   * www -- et cette balise est ce qui dit au moteur laquelle compte.
   */
  alternates: {
    canonical: '/',
  },

  openGraph: {
    type: 'website',
    locale: 'fr_FR',
    url: '/',
    siteName: SITE_NAME,
    title: SITE_TITLE,
    description: SITE_DESCRIPTION,
  },

  /*
   * `summary` et non `summary_large_image` : le depot ne fournit pas encore
   * d'image de partage, et annoncer une grande carte sans visuel donne une carte
   * vide plutot qu'une petite carte propre.
   */
  twitter: {
    card: 'summary',
    title: SITE_TITLE,
    description: SITE_DESCRIPTION,
  },

  /*
   * Indexation explicitement autorisee. C'est le defaut, mais l'ecrire ici est
   * ce qui rend visible que le choix a ete FAIT -- frontend-admin (FRONT-03)
   * ecrira l'inverse au meme endroit, et la comparaison des deux fichiers doit
   * suffire a comprendre lequel des deux est public.
   *
   * Les directives `googleBot` relevent l'apercu autorise : sans elles, Google
   * se limite a un extrait court et a une vignette d'image.
   */
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      'max-snippet': -1,
      'max-image-preview': 'large',
      'max-video-preview': -1,
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
