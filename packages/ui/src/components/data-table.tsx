'use client';

import {
  columnFilteringFeature,
  createColumnHelper,
  createFilteredRowModel,
  createPaginatedRowModel,
  createSortedRowModel,
  filterFns,
  rowPaginationFeature,
  rowSortingFeature,
  sortFns,
  tableFeatures,
  useTable,
} from '@tanstack/react-table';
import { ArrowDownIcon, ArrowUpIcon, ChevronLeftIcon, ChevronRightIcon } from 'lucide-react';
import * as React from 'react';

import { Button } from '@repo/ui/components/button';
import { Input } from '@repo/ui/components/input';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@repo/ui/components/table';
import { cn } from '@repo/ui/lib/utils';

import type { CellData, ColumnDef, RowData } from '@tanstack/react-table';

/**
 * Table de donnees triable, filtrable et paginee (FRONT-03).
 *
 * POURQUOI CE FICHIER EXISTE
 * `table.tsx`, livre par SHARED-01, est purement PRESENTATIONNEL : huit
 * composants qui habillent <table>, <thead>, <tr>... sans le moindre etat. Il
 * ne trie rien, ne filtre rien, ne pagine rien -- et le registre shadcn n'a pas
 * de `data-table` a proposer : sa page de documentation est un guide qui
 * assemble ce meme `table.tsx` avec TanStack Table. C'est la verification que
 * demandait FRONT-03, et sa conclusion : « sinon creer une extension dans le
 * package partage ».
 *
 * L'extension vit donc ici, dans `@repo/ui`, et non dans le back-office : les
 * trois applications auront des listes a trier, et une table de donnees recopiee
 * est exactement ce que la regle du depot interdit.
 *
 * TANSTACK TABLE 9, ET NON 8
 * La version 9 est une reecriture. Les exemples que l'on trouve en ligne, guide
 * shadcn compris, sont ecrits pour la 8 et NE FONCTIONNENT PAS ici :
 *   - le hook s'appelle `useTable`, plus `useReactTable` ;
 *   - les capacites s'enregistrent dans `tableFeatures`, chaque fonctionnalite
 *     avec son modele de lignes, au lieu des options `getSortedRowModel()` ;
 *   - le rendu d'une cellule passe par `<table.FlexRender cell={...} />`.
 * Une fonctionnalite non enregistree n'existe pas : ni son etat, ni ses
 * methodes. `table.setPageIndex` serait `undefined` sans `rowPaginationFeature`.
 */

/**
 * Les trois capacites que ce composant expose, et rien d'autre.
 *
 * L'ordre compte a la lecture : chaque modele de lignes suit la fonctionnalite
 * dont il depend -- TypeScript refuse un `sortedRowModel` sans
 * `rowSortingFeature`, avec un message qui nomme la fonctionnalite manquante.
 *
 * Selection de lignes, colonnes masquables, groupement : a ajouter ici le jour
 * ou un ecran en aura besoin, pas avant. Ce qui n'est pas enregistre n'est pas
 * embarque.
 */
export const dataTableFeatures = tableFeatures({
  rowSortingFeature,
  sortedRowModel: createSortedRowModel(),
  /*
   * Les fonctions de tri et de filtrage livrees avec la bibliotheque. Elles ne
   * sont pas globales en 9 : une colonne dont le `sortFn` vaut « auto » -- le
   * defaut -- resout un NOM (`text`, `alphanumeric`, `includesString`...) dans ce
   * registre, et n'y trouve rien s'il n'est pas declare.
   *
   * L'omission ne casse pas de la meme facon des deux cotes, ce qui la rend
   * penible a diagnostiquer : le tri se rabat sur une comparaison generique et
   * PARAIT fonctionner, tandis que le filtre ne trouve aucune fonction et laisse
   * simplement passer toutes les lignes -- un champ de recherche qui ne filtre
   * rien, sans la moindre erreur. Les deux cas se signalent en console, en
   * developpement seulement.
   */
  sortFns,
  filterFns,
  columnFilteringFeature,
  filteredRowModel: createFilteredRowModel(),
  rowPaginationFeature,
  paginatedRowModel: createPaginatedRowModel(),
});

export type DataTableFeatures = typeof dataTableFeatures;

/**
 * Le type des colonnes attendues par `DataTable`.
 *
 * Il est parametre par l'ensemble de capacites ci-dessus : c'est ce qui donne
 * aux definitions de colonnes l'acces aux options de tri et de filtrage, et ce
 * qui les leur refuserait si l'une des capacites disparaissait.
 */
export type DataTableColumns<TData extends RowData> = Array<
  ColumnDef<DataTableFeatures, TData, CellData>
>;

/**
 * Fabrique de definitions de colonnes, deja liee aux capacites de ce composant.
 *
 * A appeler HORS du rendu -- au niveau du module -- comme les donnees : une
 * nouvelle reference de colonnes a chaque rendu invaliderait les modeles de
 * lignes, et le tri comme la pagination se recalculeraient sans fin.
 *
 *   const column = createDataTableColumnHelper<Clinic>();
 *   const columns = column.columns([column.accessor('name', { header: 'Nom' })]);
 */
export function createDataTableColumnHelper<TData extends RowData>() {
  return createColumnHelper<DataTableFeatures, TData>();
}

type DataTableProps<TData extends RowData> = {
  columns: DataTableColumns<TData>;
  data: Array<TData>;
  /**
   * Identifiant de la colonne sur laquelle porte le champ de recherche. Omis,
   * aucun champ n'est affiche : un filtre qui ne sait pas sur quoi filtrer vaut
   * moins que pas de filtre du tout.
   */
  filterColumnId?: string;
  filterLabel?: string;
  filterPlaceholder?: string;
  pageSize?: number;
  emptyMessage?: string;
  className?: string;
};

export function DataTable<TData extends RowData>({
  columns,
  data,
  filterColumnId,
  filterLabel = 'Rechercher',
  filterPlaceholder = 'Rechercher…',
  pageSize = 10,
  emptyMessage = 'Aucun résultat.',
  className,
}: DataTableProps<TData>) {
  const filterInputId = React.useId();

  const table = useTable({
    features: dataTableFeatures,
    columns,
    data,
    /*
     * `initialState` et non `state` : la table reste proprietaire de son etat.
     * Le remonter dans l'application obligerait chaque appelant a recopier trois
     * `useState` pour le seul plaisir de les redonner tels quels.
     */
    initialState: { pagination: { pageIndex: 0, pageSize } },
  });

  const filterColumn = filterColumnId ? table.getColumn(filterColumnId) : undefined;
  const filterValue = (filterColumn?.getFilterValue() as string | undefined) ?? '';

  // Nombre de lignes APRES filtrage et avant pagination : c'est ce chiffre qui
  // renseigne l'utilisateur, pas le total brut ni le contenu de la page.
  const filteredRowCount = table.getFilteredRowModel().rows.length;
  const pageCount = table.getPageCount();
  const pageIndex = table.state.pagination.pageIndex;
  const rows = table.getRowModel().rows;

  return (
    <div className={cn('space-y-4', className)}>
      {filterColumn ? (
        <div className="space-y-2">
          <label htmlFor={filterInputId} className="sr-only">
            {filterLabel}
          </label>
          <Input
            id={filterInputId}
            type="search"
            value={filterValue}
            placeholder={filterPlaceholder}
            className="max-w-sm"
            onChange={(event) => {
              /*
               * Pas de remise a la premiere page ici : TanStack le fait de
               * lui-meme des que le filtre change. L'ecrire quand meme donnerait
               * l'illusion que c'est notre responsabilite.
               */
              filterColumn.setFilterValue(event.target.value);
            }}
          />
        </div>
      ) : null}

      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map((header) => {
                  const sorted = header.column.getIsSorted();

                  return (
                    <TableHead
                      key={header.id}
                      /*
                       * `aria-sort` sur la CELLULE d'en-tete, seul endroit ou un
                       * lecteur d'ecran le lit -- le poser sur le bouton ne
                       * produirait rien.
                       */
                      aria-sort={
                        sorted === 'asc'
                          ? 'ascending'
                          : sorted === 'desc'
                            ? 'descending'
                            : header.column.getCanSort()
                              ? 'none'
                              : undefined
                      }
                    >
                      {header.isPlaceholder ? null : header.column.getCanSort() ? (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="-ml-2.5 h-8 data-[sorted=true]:text-foreground"
                          data-sorted={sorted !== false}
                          onClick={header.column.getToggleSortingHandler()}
                        >
                          <table.FlexRender header={header} />
                          {sorted === 'asc' ? (
                            <ArrowUpIcon data-icon="inline-end" />
                          ) : sorted === 'desc' ? (
                            <ArrowDownIcon data-icon="inline-end" />
                          ) : null}
                        </Button>
                      ) : (
                        <table.FlexRender header={header} />
                      )}
                    </TableHead>
                  );
                })}
              </TableRow>
            ))}
          </TableHeader>

          <TableBody>
            {rows.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={table.getAllLeafColumns().length}
                  className="h-24 text-center text-muted-foreground"
                >
                  {emptyMessage}
                </TableCell>
              </TableRow>
            ) : (
              rows.map((row) => (
                <TableRow key={row.id}>
                  {row.getAllCells().map((cell) => (
                    <TableCell key={cell.id}>
                      <table.FlexRender cell={cell} />
                    </TableCell>
                  ))}
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {/*
       * Pagination en boutons, et non avec le composant `Pagination` du registre
       * shadcn : celui-la est fait de liens, donc destine a une pagination portee
       * par l'URL. Ici la page est un etat de la table, sans adresse propre --
       * un <a> sans href n'est ni focalisable ni actionnable au clavier.
       */}
      <nav
        aria-label="Pagination"
        className="flex items-center justify-between gap-4 text-sm text-muted-foreground"
      >
        <p aria-live="polite">
          {filteredRowCount} ligne{filteredRowCount > 1 ? 's' : ''}
          {pageCount > 1 ? ` · page ${pageIndex + 1} sur ${pageCount}` : null}
        </p>

        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={!table.getCanPreviousPage()}
            onClick={() => {
              table.previousPage();
            }}
          >
            <ChevronLeftIcon data-icon="inline-start" />
            Précédent
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={!table.getCanNextPage()}
            onClick={() => {
              table.nextPage();
            }}
          >
            Suivant
            <ChevronRightIcon data-icon="inline-end" />
          </Button>
        </div>
      </nav>
    </div>
  );
}
