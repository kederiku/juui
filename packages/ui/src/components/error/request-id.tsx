'use client';

import { CheckIcon, CopyIcon } from 'lucide-react';
import * as React from 'react';

import { Button } from '@repo/ui/components/button';
import { cn } from '@repo/ui/lib/utils';

/** Combien de temps la confirmation reste affichee, en millisecondes. */
const FEEDBACK_DURATION_MS = 2_000;

/**
 * FRONT-10 -- L'identifiant de requete, discret et copiable en un clic.
 *
 * CE QUE CE COMPOSANT REND POSSIBLE : un ticket de support diagnosticable. Le
 * meme identifiant est pose par l'API sur l'en-tete `X-Request-ID` et dans les
 * lignes de journal (BACK-11) ; sans lui, un signalement se reduit a « ca ne
 * marche pas » et personne ne retrouve la requete. Avec lui, une recherche
 * suffit. D'ou la copie : personne ne recopie a la main trente-deux caracteres
 * hexadecimaux sans se tromper.
 *
 * IL NE S'AFFICHE QUE QUAND IL EXISTE, et c'est l'appelant qui en decide, via
 * `visibleRequestId` de `resolveApiError`. Un vrai 500 ne traverse aucun
 * intergiciel CORS (ecart BACK-11) : le navigateur le presente au JavaScript
 * comme un echec reseau, sans en-tetes, donc SANS identifiant. Le cas ou il n'y
 * a rien a montrer est le cas courant, pas l'exception.
 *
 * AUCUNE DECISION DE RENDU NE REGARDE `navigator`. Ce composant s'execute aussi
 * au rendu serveur de Next, ou l'objet n'existe pas : y brancher l'affichage du
 * bouton produirait un HTML different de celui du premier rendu client, donc
 * une desynchronisation d'hydratation silencieuse. L'echec de copie se traite
 * la ou il arrive -- dans le `catch` --, et il se DIT.
 */
export function RequestId({ requestId, className }: { requestId: string; className?: string }) {
  /*
   * LA CONFIRMATION PORTE L'IDENTIFIANT QU'ELLE CONCERNE, et pas seulement un
   * etat. Sans cela, une coche « Identifiant copie » survivait au CHANGEMENT de
   * la prop -- mesure en revue : l'ecran affichait un nouvel identifiant avec la
   * confirmation de l'ancien, alors que le presse-papiers contenait toujours le
   * precedent. C'est mot pour mot la panne que ce fichier dit prevenir, et elle
   * arrive vraiment : le composant n'est pas remonte entre deux echecs
   * successifs, et chaque reponse porte un `X-Request-ID` neuf.
   *
   * Un OBJET et non deux etats : sa nouvelle identite a chaque clic relance la
   * minuterie, la ou un `setStatus('copied')` sur un statut deja `'copied'`
   * etait court-circuite par React -- deux clics rapprches et la confirmation
   * disparaissait deux secondes apres le PREMIER.
   */
  const [feedback, setFeedback] = React.useState<{
    id: string;
    status: 'copied' | 'failed';
  } | null>(null);
  const status = feedback?.id === requestId ? feedback.status : null;

  React.useEffect(() => {
    if (feedback === null) {
      return;
    }
    const timer = window.setTimeout(() => {
      setFeedback(null);
    }, FEEDBACK_DURATION_MS);
    return () => {
      window.clearTimeout(timer);
    };
  }, [feedback]);

  async function copy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(requestId);
      setFeedback({ id: requestId, status: 'copied' });
    } catch (cause) {
      // Le presse-papiers refuse hors contexte securise, et sur un document qui
      // n'a pas le focus. Le taire laisserait l'utilisateur croire a une copie
      // reussie et coller autre chose dans son signalement.
      console.warn("FRONT-10 : la copie de l'identifiant de requete a echoue.", cause);
      setFeedback({ id: requestId, status: 'failed' });
    }
  }

  const announcement =
    status === 'copied'
      ? 'Identifiant copié.'
      : status === 'failed'
        ? 'La copie a échoué. Sélectionnez l’identifiant pour le copier à la main.'
        : '';

  return (
    <div className={cn('flex flex-col gap-0.5', className)}>
      {/*
        `flex-wrap` ET `break-all` : l'identifiant fait trente-deux caracteres
        hexadecimaux, et ce bloc se pose dans des conteneurs etroits -- un
        panneau lateral, une colonne d'en-tete. Sans eux il deborde de son
        parent au lieu de passer a la ligne.
      */}
      <div className="flex flex-wrap items-center gap-x-1.5 text-xs text-muted-foreground">
        <span>Identifiant de l’incident</span>
        <code className="font-mono break-all select-all">{requestId}</code>
        <Button
          type="button"
          variant="ghost"
          size="icon-xs"
          onClick={() => {
            void copy();
          }}
        >
          {status === 'copied' ? <CheckIcon /> : <CopyIcon />}
          <span className="sr-only">Copier l’identifiant de l’incident</span>
        </Button>
      </div>
      {/*
        HORS DE TOUTE REGION `role="alert"` : celle-ci est atomique, et y placer
        cette annonce ferait relire le message d'erreur entier a chaque copie.
        La region est toujours PRESENTE, meme vide -- un lecteur d'ecran
        n'annonce que le contenu d'une region qu'il observait deja.
      */}
      <span aria-live="polite" className="sr-only">
        {announcement}
      </span>
    </div>
  );
}
