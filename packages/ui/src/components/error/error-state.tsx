import { TriangleAlertIcon } from 'lucide-react';

import { Alert, AlertDescription, AlertTitle } from '@repo/ui/components/alert';
import { cn } from '@repo/ui/lib/utils';

import type { ReactNode } from 'react';

/**
 * FRONT-10 -- Le bloc d'erreur, purement presentationnel.
 *
 * IL NE SAIT RIEN DES CODES D'ERREUR, ET C'EST LA FRONTIERE. Traduire un code
 * en phrase est du METIER : la table vit dans `@repo/api-client/errors/messages`,
 * qui rend un message deja pret. `@repo/ui` n'a aucune dependance vers le client
 * d'API -- il n'en aurait pas la resolution --, et un composant qui connaitrait
 * `identity.account.not_found` n'aurait plus rien de generique.
 *
 * `children` EST RENDU HORS DE L'ALERTE, ET C'EST DELIBERE. `role="alert"`
 * implique `aria-atomic="true"` : tout ce qu'il contient est relu EN ENTIER a
 * chaque changement. Une confirmation de copie placee dedans ferait donc
 * reannoncer le message d'erreur complet a chaque clic, puis une seconde fois
 * quand elle disparait. Le bloc d'identifiant de requete est donc un FRERE de
 * l'alerte, pas un descendant.
 */
export function ErrorState({
  title,
  message,
  className,
  children,
}: {
  /**
   * Le titre du bloc, facultatif et SANS DEFAUT.
   *
   * Un defaut « Une erreur est survenue » aurait double le repli generique de
   * `resolveApiError`, qui commence par ces mots exacts -- l'ecran affichait
   * alors deux fois la meme phrase, precisement dans le cas le plus frequent en
   * production. Un titre se donne quand l'appelant sait nommer ce qui a echoue.
   */
  title?: string;
  /** La phrase a afficher, deja traduite. Jamais `error.message` du serveur. */
  message: string;
  className?: string;
  /** L'identifiant de requete, ou toute mention discrete sous l'alerte. */
  children?: ReactNode;
}) {
  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      <Alert variant="destructive">
        <TriangleAlertIcon />
        {title === undefined ? null : <AlertTitle>{title}</AlertTitle>}
        <AlertDescription>{message}</AlertDescription>
      </Alert>
      {children}
    </div>
  );
}
