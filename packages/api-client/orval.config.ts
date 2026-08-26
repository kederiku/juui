import { defineConfig } from 'orval';

/**
 * SHARED-03 -- Configuration du generateur de client d'API.
 *
 * POURQUOI CE FICHIER EXISTE
 * Le serveur FastAPI est l'unique source de verite du contrat (ADR-0007). Ce
 * fichier decrit comment ce contrat devient du TypeScript : des types, des
 * hooks TanStack Query, et des schemas Zod. Rien de ce qu'il produit ne
 * s'edite : la correction d'un champ se fait cote backend, puis ici par
 * regeneration.
 *
 * DEUX SORTIES, ET NON UNE
 * Orval ne sait produire qu'un `client` par sortie. Les hooks et les schemas Zod
 * sont donc deux clefs distinctes, sur la meme entree -- c'est la forme imposee,
 * pas un choix.
 *
 * CE FICHIER EST TYPE, ET C'EST OPERANT
 * `defineConfig` verifie chaque option, et tsconfig.json l'inclut dans le
 * projet : une clef mal orthographiee echoue a `pnpm typecheck`, au lieu de
 * produire en silence une sortie incomplete.
 */

/**
 * En-tete depose en tete de CHAQUE fichier genere.
 *
 * AUCUNE VALEUR DYNAMIQUE, ET C'EST DELIBERE. L'en-tete par defaut d'Orval
 * inscrit sa propre version dans chaque fichier : une montee de version
 * produirait alors un diff sur toute la sortie, indiscernable d'un changement de
 * contrat -- exactement ce que l'ADR-0007 demande de garder lisible.
 */
const generatedFileHeader = (): string[] => [
  'SHARED-03 -- FICHIER GENERE PAR ORVAL. NE PAS EDITER.',
  "Source : packages/api-client/openapi.json, exporte depuis l'API FastAPI.",
  'Regeneration :  make generate-api',
  'Sortie versionnee (ADR-0007) : un diff ici est un changement de contrat.',
];

export default defineConfig({
  // --- Sortie 1 : types et hooks TanStack Query ------------------------------
  api: {
    input: {
      // UN FICHIER, et non http://localhost:8000/openapi.json : la generation ne
      // doit dependre ni d'un backend demarre ni du reseau. C'est la condition
      // du controle « regenerer ne produit aucun diff » (ADR-0007, ADR-0019), et
      // /openapi.json est de toute facon ferme en production.
      target: './openapi.json',
    },
    output: {
      // Ce chemin ne produit AUCUN fichier en mode tags-split : Orval n'en
      // retient que le repertoire et l'extension.
      target: './src/generated/api/juui.ts',

      // Schemas CENTRALISES plutot qu'un jeu par etiquette. `ReadinessComponents`
      // est deja partage entre deux reponses ; a l'echelle du produit, les
      // modeles traversent les etiquettes -- une clinique apparaitra dans
      // identity comme dans organization. Sans cette clef, tags-split les
      // recopierait dans chaque dossier, autant de types nominalement distincts.
      schemas: './src/generated/api/model',

      mode: 'tags-split',
      client: 'react-query',

      // Defaut d'Orval 8, ecrit pour etre visible : c'est lui qui fixe la
      // signature du mutator -- (url: string, options: RequestInit).
      httpClient: 'fetch',

      // PAS DE `baseUrl`. Orval sait injecter une expression d'environnement
      // dans l'URL construite, et c'est inutilisable ici : le depot a DEUX
      // adresses -- NEXT_PUBLIC_API_URL pour le navigateur, API_INTERNAL_URL
      // pour le serveur Next -- et le choix se fait a l'EXECUTION, pas au moment
      // de la generation. Sans cette clef l'URL generee est relative, et c'est
      // le mutator qui prefixe : la base URL reste ou le ticket la place, et le
      // genere reste un pur contrat, sans connaissance de l'environnement.

      // Efface la sortie avant d'ecrire. Sans cela, une etiquette retiree du
      // backend -- ou une operation renommee -- laisserait un fichier orphelin
      // qui compile toujours et expose un hook vers une route disparue : la
      // derive silencieuse contre laquelle l'ADR-0007 a ete ecrit. Sans danger
      // ici : src/generated/api/ ne contient aucun fichier ecrit a la main, et
      // la sortie Zod vit dans un arbre voisin.
      clean: true,

      // AUCUN INDEX. Le critere « pas de barrel geant » se joue d'abord ici :
      // sans index.ts, il n'existe aucun fichier capable de tout re-exporter.
      // Effet de bord bienvenu, l'ordre des lignes d'un baril auto-genere suit
      // le parcours du systeme de fichiers -- APFS sur le poste, ext4 sur le
      // runner : une source de diff qui ne vient d'aucun changement de contrat.
      indexFiles: false,

      // Noms de fichiers en kebab-case, comme partout dans le depot
      // (data-table.tsx, use-mobile.ts). A defaut, `medical_records` sortirait
      // en medicalRecords/medicalRecords.ts.
      namingConvention: 'kebab-case',

      // PAS DE `formatter`. Le mettre a 'prettier' serait une option ecrite et
      // sans effet : .prettierignore exclut `**/generated/`, et Prettier saute
      // ce qu'il ignore, meme sur invocation nommee. Le depot a deja arbitre --
      // « regenere a chaque modification d'un contrat, le reformater serait
      // perdu » -- et ce fichier s'y tient.

      // PAS DE `mock`. Orval sait produire des handlers MSW ; l'outillage de
      // test frontend appartient a QA-02, qui decidera.

      override: {
        // Le point unique par lequel passe tout appel HTTP.
        mutator: {
          path: './src/mutator.ts',
          name: 'customFetch',
        },

        header: generatedFileHeader,

        // Unions de chaines, et non objets `as const` ni enums. Les `Literal` de
        // Pydantic -- status "alive" | "ready" | "unready", composants "ok" |
        // "unreachable" -- deviendraient autant d'objets PRESENTS A L'EXECUTION,
        // donc du poids de bundle pour une information que le type porte deja
        // entierement. Accessoirement, c'est la principale source d'imports a la
        // fois type et valeur, que `verbatimModuleSyntax` refuse.
        enumGenerationType: 'union',

        fetch: {
          // Le hook rend LA DONNEE, pas l'enveloppe { data, status, headers }.
          // Sinon chaque site d'appel s'ecrirait `query.data?.data.status`, et
          // le cache de TanStack Query porterait un objet Headers non
          // serialisable. Ce que l'enveloppe apportait -- l'en-tete
          // X-Request-ID -- ne sert qu'en cas d'erreur, et le mutator l'attache
          // deja a l'ApiError qu'il leve.
          includeHttpResponseReturnType: false,
        },

        query: {
          useQuery: true,

          // `useMutation` N'EST PAS ECRIT ICI, ET C'EST UNE CORRECTION.
          // Son defaut est « vrai pour les verbes autres que GET » ; le poser
          // explicitement a `true` le rend vrai pour TOUTES les operations, et
          // les deux sondes GET sortaient alors en useMutation -- verifie a la
          // premiere generation. Le defaut fait exactement ce qu'on veut.

          // Rien dans le contrat ne pagine par curseur : l'ADR-0017 retient une
          // pagination par offset (page / page_size), qui se sert parfaitement
          // avec useQuery. A rouvrir si une route l'exige un jour.
          useInfinite: false,

          // A rouvrir par FRONT-04, qui possede le QueryClientProvider et
          // decidera de la strategie de chargement des trois applications.
          useSuspenseQuery: false,

          // Le signal d'abandon de TanStack Query descend jusqu'au RequestInit
          // du mutator : une requete annulee -- navigation, saisie -- coupe
          // reellement la connexion. Defaut d'Orval, ecrit parce que le mutator
          // en depend explicitement : il distingue un abandon d'une panne.
          signal: true,

          // FRONT-04 batira sa fabrique de clefs sur getXxxQueryKey : sans
          // export, l'invalidation ciblee apres une mutation redeviendrait un
          // tableau recopie a la main.
          shouldExportQueryKey: true,

          // AUCUNE option de requete par defaut ici -- staleTime, retry, gcTime.
          // La politique de cache appartient au QueryClient de FRONT-04, en un
          // seul endroit ; l'inscrire dans le genere la figerait par operation
          // et la rendrait invisible.
        },
      },
    },
  },

  // --- Sortie 2 : schemas Zod ------------------------------------------------
  zod: {
    input: {
      target: './openapi.json',
    },
    output: {
      target: './src/generated/zod/juui.ts',
      client: 'zod',
      mode: 'tags-split',
      clean: true,
      indexFiles: false,
      namingConvention: 'kebab-case',
      override: {
        header: generatedFileHeader,
        zod: {
          // Explicite plutot que 'auto' : la version se lit ici et se rapproche
          // du `zod` epingle dans package.json, au lieu d'etre deduite de ce que
          // l'installation a resolu.
          version: 4,

          // ASYMETRIQUE, ET C'EST TOUT L'ENJEU. Strict sur ce que l'on ENVOIE :
          // une clef en trop dans un corps est une faute de notre cote, elle
          // doit echouer tot. Permissif sur ce que l'on RECOIT : un champ ajoute
          // par le backend ne doit pas faire echouer un client deja deploye --
          // ce serait transformer une evolution retro-compatible en panne.
          strict: { param: true, query: true, header: false, body: true, response: false },

          // Une valeur de chaine de requete arrive toujours en chaine. Sans
          // coercition, le page / page_size de l'ADR-0017 echouerait sur un
          // schema attendant un entier.
          coerce: { param: true, query: true },

          // Un schema par statut HTTP doublerait la sortie pour rien : le corps
          // de /health/ready est le meme en 200 et en 503, et les erreurs
          // partagent un format unique (BACK-09). A rouvrir si un statut prend
          // un jour un corps different.
          generateEachHttpStatus: false,
        },
      },
    },
  },
});
