'use client';

import { Button } from '@repo/ui/components/button';
import { useTheme } from '@repo/ui/components/theme-provider';
import { MoonIcon, SunIcon } from 'lucide-react';

/**
 * Bascule entre theme clair et theme sombre (FRONT-01).
 *
 * `useTheme` est pris a `@repo/ui`, qui le re-exporte : l'application ne depend
 * jamais de next-themes directement, si bien qu'en changer un jour ne toucherait
 * que le package.
 *
 * Les deux icones sont rendues, et c'est le CSS qui masque la bonne. Choisir en
 * JavaScript imposerait d'attendre le montage pour connaitre le theme resolu --
 * donc un bouton vide au premier rendu, ou une divergence d'hydratation.
 */
export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();

  return (
    <Button
      variant="outline"
      size="icon"
      onClick={() => setTheme(resolvedTheme === 'dark' ? 'light' : 'dark')}
    >
      <SunIcon className="dark:hidden" />
      <MoonIcon className="hidden dark:block" />
      <span className="sr-only">Changer de thème</span>
    </Button>
  );
}
