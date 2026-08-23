import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

/**
 * Fusionne des classes Tailwind en resolvant les conflits.
 *
 * `clsx` aplatit les formes conditionnelles (chaines, tableaux, objets) ;
 * `twMerge` tranche ensuite les classes qui se disputent la meme propriete --
 * `cn('px-2', 'px-4')` rend `px-4`, la ou une simple concatenation laisserait
 * l'ordre du CSS decider. C'est ce qui rend surchargeable le `className` de
 * chaque composant de cette bibliotheque.
 *
 * Livre par le registre shadcn, expose ici sous `@repo/ui/lib/utils`.
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
