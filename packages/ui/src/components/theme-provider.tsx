'use client';

import { ThemeProvider as NextThemesProvider, useTheme } from 'next-themes';

import type * as React from 'react';

/**
 * Fournisseur du theme clair/sombre, partage par les trois applications
 * (SHARED-01).
 *
 * Ecrit ici plutot que dans chaque application a dessein : c'est lui qui pose
 * la classe `.dark` sur laquelle repose le `@custom-variant dark` de
 * `globals.css`. Trois copies finiraient par diverger, et le theme avec elles.
 *
 * A monter dans le layout racine de chaque application :
 *
 *   <html lang="fr" suppressHydrationWarning>
 *     <body>
 *       <ThemeProvider>{children}</ThemeProvider>
 *     </body>
 *   </html>
 *
 * `suppressHydrationWarning` sur <html> n'est pas optionnel : next-themes
 * ecrit la classe avant l'hydratation pour eviter le flash de theme clair, et
 * le rendu serveur ne peut pas la prevoir.
 */
function ThemeProvider({ children, ...props }: React.ComponentProps<typeof NextThemesProvider>) {
  return (
    <NextThemesProvider
      // `class` et non `data-theme` : c'est la forme qu'attend le
      // `@custom-variant dark (&:is(.dark *))` de globals.css.
      attribute="class"
      defaultTheme="system"
      enableSystem
      // Neutralise les transitions CSS le temps du basculement, sinon chaque
      // couleur de la page s'anime separement.
      disableTransitionOnChange
      {...props}
    >
      {children}
    </NextThemesProvider>
  );
}

/**
 * Re-exporte pour que les applications n'aient pas a dependre de next-themes
 * directement : `@repo/ui` est la seule frontiere avec cette bibliotheque.
 */
export { ThemeProvider, useTheme };
