'use client';

import { QueryClientProvider, useQueryClient } from '@tanstack/react-query';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';
import { useState } from 'react';

import { createQueryClient } from './query-client';

import type { QueryClient } from '@tanstack/react-query';
import type { ReactNode } from 'react';

/**
 * L'unique QueryClient du NAVIGATEUR, et rien d'autre.
 *
 * POURQUOI UN ETAT DE MODULE ICI, ALORS QUE query-client.ts SE L'INTERDIT
 * Parce qu'il est garde, et que la garde est ce qui compte. Sur le serveur, la
 * branche n'est jamais atteinte : chaque appel fabrique un client neuf, et rien
 * n'est retenu -- l'avertissement en tete de runtime.ts est tenu. Dans le
 * navigateur, il n'y a qu'un utilisateur, et c'est justement d'un exemplaire
 * unique qu'on a besoin.
 *
 * CE QU'IL EVITE, ET C'EST MESURE. `useState(createQueryClient)` seul ne
 * suffit pas : React JETTE l'etat d'un composant qui suspend avant d'avoir
 * commite, et rejoue l'initialiseur a chaque tentative de rendu. Une sonde
 * posee sous le fournisseur, suspendue par un `use(promise)` sans frontiere
 * `<Suspense>` intermediaire, a compte TROIS QueryClient distincts la ou il en
 * faut un -- et le client finalement commite est neuf, donc son cache est vide
 * et ses requetes en vol sont perdues. App Router n'interpose aucune frontiere
 * implicite entre le layout racine et la page : le premier `use()`, `lazy()` ou
 * composant client asynchrone rouvrirait la panne, sans erreur ni
 * avertissement. Avec cette fonction, la meme sonde compte UN.
 */
let browserQueryClient: QueryClient | undefined;

/**
 * Rend le client a poser dans le fournisseur : celui du navigateur, ou un
 * client NEUF a chaque appel cote serveur.
 */
function getQueryClient(): QueryClient {
  if (typeof window === 'undefined') {
    return createQueryClient();
  }
  browserQueryClient ??= createQueryClient();
  return browserQueryClient;
}

/**
 * FRONT-04 -- Le fournisseur de donnees, partage par les trois applications.
 *
 * UN SEUL FICHIER POUR TROIS APPLICATIONS, comme le `ThemeProvider` de
 * `@repo/ui` (SHARED-01) : trois copies finiraient par diverger, et la politique
 * de cache avec elles. C'est aussi pourquoi les applications ne declarent pas
 * `@tanstack/react-query` (ecart SHARED-03) -- deux exemplaires rendraient ce
 * fournisseur INVISIBLE aux hooks, sans la moindre erreur de compilation.
 *
 * LE CLIENT EST CREE DANS UN INITIALISEUR DE useState, ET JAMAIS AU NIVEAU DU
 * MODULE SANS GARDE. La raison est mot pour mot celle de l'avertissement en
 * tete de runtime.ts : sur le serveur Next, un module est partage par TOUTES
 * les requetes du processus, et un QueryClient de module y servirait le cache
 * d'un utilisateur a un autre. L'initialiseur appelle donc `getQueryClient`,
 * qui fabrique un client neuf cote serveur et n'en retient un que dans le
 * navigateur -- voir son commentaire, et la mesure qui le motive. Le pendant
 * des composants serveur est `getServerQueryClient` (query-server.ts).
 *
 * A monter dans le layout racine de chaque application, DANS le ThemeProvider :
 *
 *   <body className="font-sans antialiased">
 *     <ThemeProvider>
 *       <QueryProvider>{children}</QueryProvider>
 *     </ThemeProvider>
 *   </body>
 *
 * PAS DE app/providers.tsx, ET C'EST UN CHOIX. Ce composant porte deja
 * `'use client'` : un layout reste composant serveur le monte directement,
 * comme il monte deja le `ThemeProvider`. Un fichier intermediaire par
 * application aurait ouvert un SECOND endroit ou l'ordre des fournisseurs se
 * decide -- trois occasions de diverger, quand le ticket refuse par ailleurs
 * « trois configurations divergentes ». FRONT-03 avait deja tranche dans ce
 * sens en montant `TooltipProvider` dans le layout qui en a besoin.
 *
 * CE QUE CE FICHIER NE FAIT PAS
 * Il ne sait rien du groupe actif et ne purge rien : la bascule de groupe et sa
 * purge appartiennent a FRONT-08, qui trouvera dans `tenantScopeKey`
 * (query-keys.ts) le prefixe qui la rend exacte. Il ne branche pas non plus le
 * traitement du 401 -- il est deja pose par la fabrique du client, et c'est
 * FRONT-07 qui remplacera la fonction (unauthorized.ts).
 */
function QueryProvider({ children }: { children: ReactNode }) {
  // LA FONCTION EST PASSEE, PAS SON RESULTAT. `useState(getQueryClient())`
  // appellerait la fabrique a CHAQUE rendu pour n'en garder qu'un resultat.
  const [queryClient] = useState(getQueryClient);

  return (
    <QueryClientProvider client={queryClient}>
      {children}
      {/*
       * HORS PRODUCTION SEULEMENT -- ET LA MESURE A CORRIGE CE COMMENTAIRE.
       * On croirait que cette garde est ce qui retire les Devtools du bundle.
       * Ce n'est pas elle : `@tanstack/react-query-devtools` s'auto-neutralise,
       * son point d'entree valant
       * `process.env.NODE_ENV !== 'development' ? () => null : ...`. Contre-
       * epreuve faite -- garde retiree, `next build` rejoue : le panneau lui-
       * meme (~600 Ko de `@tanstack/query-devtools`) reste ABSENT dans les deux
       * cas ; seul l'element JSX reapparait, pour 174 octets. Ce sont donc DEUX
       * mecanismes, et le second est celui qui tient le critere.
       *
       * Cette ligne-ci reste pour ce qu'elle fait vraiment : elle retire
       * l'element de l'arbre au lieu d'y rendre une souche, et elle ecrit
       * l'intention a l'endroit du montage. La mesure complete, contre-epreuve
       * comprise, est sur la page « Donnees cote client ».
       *
       * `bottom-left` : `sonner` (SHARED-01) n'est monte dans aucune
       * application a ce jour et ne fixe pas sa position, mais il s'affiche par
       * defaut en bas a droite -- le jour ou une application le montera, les
       * deux ne se recouvriront pas.
       */}
      {process.env.NODE_ENV !== 'production' && (
        <ReactQueryDevtools initialIsOpen={false} buttonPosition="bottom-left" />
      )}
    </QueryClientProvider>
  );
}

/**
 * Re-exporte pour que les applications n'aient pas a dependre de
 * `@tanstack/react-query` directement -- elles ne le POURRAIENT pas : elles ne
 * la declarent pas (ecart SHARED-03) et le node_modules strict de pnpm interdit
 * d'importer ce qu'on ne declare pas. Meme geste que le `useTheme` re-exporte
 * par `@repo/ui`. C'est par ce hook que passeront l'invalidation apres une
 * mutation et la purge de FRONT-08.
 */
export { QueryProvider, useQueryClient };
