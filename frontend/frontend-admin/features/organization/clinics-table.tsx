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
 *
 * DANS `features/organization/` DEPUIS FRONT-09, et pas dans `components/` : il
 * porte du METIER -- une clinique, son groupe, son statut d'exploitation -- ce
 * qui le range du cote du sujet et non du cote du shell. Le nom de la feature
 * suit celui du module backend `organization`, donc celui du fichier qu'Orval
 * produira en `tags-split` et que FRONT-19 branchera ici a la place du jeu de
 * donnees ci-dessous.
 */

/*
 * Les statuts tels que le module `organization` les nommera : des valeurs
 * ANGLAISES, comme le reste du code, et un libelle francais rendu a l'ecran.
 * Ecrire directement « en attente » dans la donnee melangerait les deux, et le
 * premier statut qui viendrait de l'API ne correspondrait a aucun cas.
 */
type ClinicStatus = 'active' | 'pending' | 'suspended';

/*
 * A SAVOIR : la colonne se trie sur la VALEUR, pas sur ce libelle. Les deux
 * ordres coincident aujourd'hui par hasard -- `a < p < s` comme
 * `active < en attente < suspendue` -- et divergeront au premier statut ajoute
 * (`archived` rendrait « archivee », qui vient en tete en francais). Ce sera a
 * FRONT-19 de poser un `sortFn` explicite quand ces donnees viendront de l'API ;
 * en poser un sur douze lignes ecrites en dur serait du decor.
 */
const STATUS_LABELS: Record<ClinicStatus, string> = {
  active: 'active',
  pending: 'en attente',
  suspended: 'suspendue',
};

type Clinic = {
  name: string;
  city: string;
  veterinarians: number;
  status: ClinicStatus;
};

/*
 * Declarees au niveau du module, comme les colonnes ci-dessous : une nouvelle
 * reference a chaque rendu invaliderait les modeles de lignes de la table, qui
 * recalculerait tri et pagination sans fin.
 */
const CLINICS: Array<Clinic> = [
  { name: 'Clinique des Tilleuls', city: 'Nantes', veterinarians: 6, status: 'active' },
  { name: 'Cabinet du Vieux Port', city: 'Marseille', veterinarians: 3, status: 'active' },
  { name: 'Vétérinaires de la Garonne', city: 'Toulouse', veterinarians: 8, status: 'pending' },
  { name: 'Clinique Saint-Roch', city: 'Montpellier', veterinarians: 4, status: 'active' },
  { name: 'Cabinet des Quatre Chemins', city: 'Lille', veterinarians: 2, status: 'suspended' },
  { name: 'Clinique de la Rade', city: 'Brest', veterinarians: 5, status: 'active' },
  { name: 'Centre vétérinaire Bellecour', city: 'Lyon', veterinarians: 11, status: 'active' },
  { name: 'Cabinet des Chartrons', city: 'Bordeaux', veterinarians: 3, status: 'pending' },
  { name: 'Clinique du Parc', city: 'Strasbourg', veterinarians: 7, status: 'active' },
  { name: 'Cabinet de la Cathédrale', city: 'Reims', veterinarians: 2, status: 'active' },
  { name: 'Clinique des Dunes', city: 'Dunkerque', veterinarians: 4, status: 'suspended' },
  { name: 'Centre vétérinaire Massena', city: 'Nice', veterinarians: 9, status: 'active' },
];

const column = createDataTableColumnHelper<Clinic>();

const columns = column.columns([
  column.accessor('name', { header: 'Clinique' }),
  column.accessor('city', { header: 'Ville' }),
  column.accessor('veterinarians', {
    header: 'Vétérinaires',
    cell: (info) => <span className="tabular-nums">{info.getValue()}</span>,
  }),
  column.accessor('status', {
    header: 'Statut',
    cell: (info) => {
      const status = info.getValue();

      return (
        <Badge variant={status === 'active' ? 'secondary' : 'outline'}>
          {STATUS_LABELS[status]}
        </Badge>
      );
    },
  }),
]);

export function ClinicsTable() {
  return (
    <DataTable
      columns={columns}
      data={CLINICS}
      filterColumnId="name"
      filterLabel="Rechercher une clinique"
      filterPlaceholder="Rechercher une clinique…"
      pageSize={5}
      emptyMessage="Aucune clinique ne correspond à cette recherche."
    />
  );
}
