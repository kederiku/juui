import { CliniquesTable } from '@/components/cliniques-table';

import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Cliniques',
};

/**
 * Liste des cliniques (FRONT-03).
 *
 * Deuxieme raison d'etre de cette page : donner au fil d'Ariane un deuxieme
 * niveau. Un fil d'Ariane qui n'affiche jamais qu'un seul element ne prouve
 * rien.
 */
export default function CliniquesPage() {
  return (
    <>
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">Cliniques</h1>
        <p className="text-muted-foreground">
          Tri par colonne, recherche et pagination — les trois capacités que le composant{' '}
          <code className="font-mono">Table</code> de <code className="font-mono">@repo/ui</code> ne
          couvrait pas, et que son extension <code className="font-mono">DataTable</code> apporte.
        </p>
      </header>

      <CliniquesTable />
    </>
  );
}
