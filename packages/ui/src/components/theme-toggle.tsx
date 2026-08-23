'use client';

import { MoonIcon, SunIcon } from 'lucide-react';

import { Button } from '@repo/ui/components/button';
import { useTheme } from '@repo/ui/components/theme-provider';

/**
 * Bascule entre theme clair et theme sombre.
 *
 * Ecrite en FRONT-01 dans `frontend-professional`, remontee ici en FRONT-02 :
 * la deuxieme application en avait besoin, et le ticket interdit de dupliquer
 * un composant d'une application a l'autre. Elle rejoint donc le
 * `theme-provider` dont elle est le pendant -- l'un pose la classe `.dark`,
 * l'autre la commande.
 *
 * `useTheme` est pris a `@repo/ui`, qui le re-exporte : les applications ne
 * dependent jamais de next-themes directement, si bien qu'en changer un jour ne
 * toucherait que ce package.
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
