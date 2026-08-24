'use client';

import { Badge } from '@repo/ui/components/badge';
import { createDataTableColumnHelper, DataTable } from '@repo/ui/components/data-table';

/**
 * Demonstration de la `DataTable` de `@repo/ui` (FRONT-03).
 *
 * Les donnees sont ecrites en dur : ni API ni cache ne sont branches avant
 * FRONT-04. Ce qu'elles servent a montrer, c'est que l'extension du package
 * partage trie, filtre et pagine -- les trois capacites que le ticket demande de
 * verifier sur le composant `Table`, qui ne les couvrait pas.
 *
 * Composant CLIENT, et pas par gout : les definitions de colonnes portent des
 * fonctions de rendu, et une fonction ne traverse pas la frontiere serveur ->
 * client. La page qui l'affiche reste, elle, un composant serveur, ce qui lui
 * laisse ses metadonnees.
 */

type Clinique = {
  nom: string;
  ville: string;
  veterinaires: number;
  statut: 'active' | 'en attente' | 'suspendue';
};

/*
 * Declarees au niveau du module, comme les colonnes ci-dessous : une nouvelle
 * reference a chaque rendu invaliderait les modeles de lignes de la table, qui
 * recalculerait tri et pagination sans fin.
 */
const CLINIQUES: Array<Clinique> = [
  { nom: 'Clinique des Tilleuls', ville: 'Nantes', veterinaires: 6, statut: 'active' },
  { nom: 'Cabinet du Vieux Port', ville: 'Marseille', veterinaires: 3, statut: 'active' },
  { nom: 'Vétérinaires de la Garonne', ville: 'Toulouse', veterinaires: 8, statut: 'en attente' },
  { nom: 'Clinique Saint-Roch', ville: 'Montpellier', veterinaires: 4, statut: 'active' },
  { nom: 'Cabinet des Quatre Chemins', ville: 'Lille', veterinaires: 2, statut: 'suspendue' },
  { nom: 'Clinique de la Rade', ville: 'Brest', veterinaires: 5, statut: 'active' },
  { nom: 'Centre vétérinaire Bellecour', ville: 'Lyon', veterinaires: 11, statut: 'active' },
  { nom: 'Cabinet des Chartrons', ville: 'Bordeaux', veterinaires: 3, statut: 'en attente' },
  { nom: 'Clinique du Parc', ville: 'Strasbourg', veterinaires: 7, statut: 'active' },
  { nom: 'Cabinet de la Cathédrale', ville: 'Reims', veterinaires: 2, statut: 'active' },
  { nom: 'Clinique des Dunes', ville: 'Dunkerque', veterinaires: 4, statut: 'suspendue' },
  { nom: 'Centre vétérinaire Massena', ville: 'Nice', veterinaires: 9, statut: 'active' },
];

const column = createDataTableColumnHelper<Clinique>();

const columns = column.columns([
  column.accessor('nom', { header: 'Clinique' }),
  column.accessor('ville', { header: 'Ville' }),
  column.accessor('veterinaires', {
    header: 'Vétérinaires',
    cell: (info) => <span className="tabular-nums">{info.getValue()}</span>,
  }),
  column.accessor('statut', {
    header: 'Statut',
    cell: (info) => {
      const statut = info.getValue();

      return <Badge variant={statut === 'active' ? 'secondary' : 'outline'}>{statut}</Badge>;
    },
  }),
]);

export function CliniquesTable() {
  return (
    <DataTable
      columns={columns}
      data={CLINIQUES}
      filterColumnId="nom"
      filterLabel="Rechercher une clinique"
      filterPlaceholder="Rechercher une clinique…"
      pageSize={5}
      emptyMessage="Aucune clinique ne correspond à cette recherche."
    />
  );
}
