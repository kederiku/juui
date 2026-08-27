---
title: Les trois applications
description: 'Ce que fait chaque application Next.js : le socle commun FRONT-01 à 03, le volet SEO de frontend-individual et le back-office.'
---

# Les trois applications

Trois applications Next.js, un seul patron — `frontend-professional` fixe le
socle, `frontend-individual` y ajoute le volet SEO de la seule application
publique, et `frontend-admin` referme tout derrière une session.

## Ce que fait une application (FRONT-01 à FRONT-03)

Les trois existent : `frontend-professional` (FRONT-01), `frontend-individual`
(FRONT-02) et `frontend-admin` (FRONT-03). La première sert de **patron**, et
les deux suivantes ont repris ces sept points à l'identique sans en amender
aucun. Seuls les distinguent leur port, leurs métadonnées, et ce que décrivent
les deux sections suivantes — le volet SEO de la seule application publique, et
le back-office de la seule qui soit entièrement privée.

1. Cinq dépendances de workspace — `@repo/ui`, `@repo/api-client`,
   `@repo/tailwind-config`, `@repo/typescript-config` et `@repo/eslint-config`,
   toutes en `"workspace:*"` — et
   `transpilePackages: ['@repo/api-client', '@repo/ui']` dans `next.config.ts`,
   les deux packages étant livrés en TypeScript non compilé. Le client d'API est
   arrivé avec SHARED-03 : [Le client d'API généré](./client-api-genere.md).
2. `export { default } from '@repo/tailwind-config/postcss.config';` dans son
   `postcss.config.mjs`.
3. Un `app/globals.css` à elle, qui ré-importe celui de `@repo/ui` et **énumère
   ses dossiers de code** :

   ```css
   @import '@repo/ui/globals.css';

   @source '../app/**/*.{ts,tsx}';
   @source '../features/**/*.{ts,tsx}';
   @source '../components/**/*.{ts,tsx}';
   ```

   C'est ce fichier-là, et non celui du package, que `app/layout.tsx` importe.
   La troisième ligne est arrivée avec FRONT-09, en même temps que le dossier
   qu'elle nomme. FRONT-01 présentait ces `@source` comme une réparation — sans
   eux, les classes de l'application auraient été purgées. **La mesure dit
   autre chose** : construire une application avec ce fichier privé de ses trois
   lignes produit un CSS qui contient encore les classes de `app/` et de
   `features/`, la détection automatique de Tailwind v4 balayant déjà le dossier
   de l'application. Elles restent parce qu'une énumération vaut mieux qu'un
   comportement implicite — et parce qu'une énumération **incomplète** serait le
   pire des trois états.

4. `<html lang="fr" suppressHydrationWarning>`, puis `<ThemeProvider>` et
   `<QueryProvider>` autour de l'arbre — sans `suppressHydrationWarning`,
   next-themes provoque un avertissement d'hydratation à chaque rendu. Le
   fournisseur de données est arrivé avec FRONT-04 :
   [Données côté client](./donnees-cote-client.md).
5. Une police chargée avec `next/font` et exposée en `--font-juui-sans` sur
   `<html>` : c'est la variable que lit le `--font-sans` du preset. La classe
   `font-sans` doit en outre être posée sur `<body>` — le thème définit le token,
   il ne l'applique à aucun élément.
6. Un `tsconfig.json` qui étend `@repo/typescript-config/nextjs.json` et déclare
   chez lui ce qu'un fichier partagé ne peut pas porter — ses `paths` (`@/*` et
   `"@repo/ui/*": ["../../packages/ui/src/*"]`), son `include` et son `exclude`.
   `@repo/api-client` n'y figure pas, et c'est délibéré : la résolution
   `bundler` du socle partagé lit la carte `exports` du package et n'a besoin
   d'aucune entrée — vérifié plutôt que supposé (registre des écarts, SHARED-03).
7. `output: 'standalone'` **et** un `outputFileTracingRoot` pointant la racine du
   dépôt. Le second n'est pas facultatif dans un monorepo : sans lui, le traçage
   part du dossier de l'application et n'embarque pas les dépendances atteintes
   par les liens symboliques pnpm. La sortie se construit alors sans erreur et
   échoue au démarrage.

Ni `src/`, ni `tailwind.config.ts`, ni `prettier.config.mjs` local : le code
applicatif vit dans `app/`, `features/`, `components/` et `lib/`, le thème est
du CSS depuis Tailwind v4, et une configuration Prettier locale devrait
redéfinir son `tailwindStylesheet` sous peine de trier les classes sans le
thème.

Le partage entre ces quatre dossiers — et la règle ESLint qui l'impose — a sa
page : [Structure par domaine](./structure-par-domaine.md).

## Le volet SEO de `frontend-individual`

Des trois applications, `frontend-individual` est la seule à être **publique**
et destinée à l'indexation — les deux autres sont des espaces authentifiés.
C'est la seule différence de fond avec le patron, et elle tient dans quatre
fichiers :

| Fichier           | Rôle                                                                                                                       |
| ----------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `lib/site-url.ts` | L'URL canonique du site, lue une fois dans `SITE_URL`. Les trois autres s'y réfèrent au lieu d'en garder chacun une copie. |
| `app/robots.ts`   | Sert `/robots.txt` : indexation autorisée, et renvoi vers le sitemap.                                                      |
| `app/sitemap.ts`  | Sert `/sitemap.xml` : les pages publiques — l'accueil pour l'instant.                                                      |
| `app/layout.tsx`  | `metadataBase`, balise canonique, Open Graph, carte Twitter, directives `robots` et `googlebot`.                           |

`site-url.ts` a quitté `app/` avec FRONT-09 : ce n'est ni une route ni un
fichier de métadonnées, c'est de la configuration que trois fichiers de routage
partagent. `app/` ne porte plus que du routage, et le garde-fou tient la flèche
dans ce sens-là — `app/` lit `lib/`, jamais l'inverse.

Rien n'est routé à la main : dans l'App Router, `robots.ts` et `sitemap.ts` sont
des **fichiers de métadonnées** — leur nom suffit à servir la route qui leur
correspond.

**Tout est produit au build.** La page d'accueil n'appelle aucune API dynamique,
Next la prérend donc, comme les deux fichiers de métadonnées. `pnpm build` le
dit lui-même, `○` valant « prerendered as static content » :

```text
Route (app)
┌ ○ /
├ ○ /_not-found
├ ○ /robots.txt
└ ○ /sitemap.xml
```

C'est la génération statique que demande le ticket, obtenue sans rien forcer :
aucun `export const dynamic = 'force-static'` n'est écrit nulle part. Le jour où
une page aura besoin d'un rendu par requête, elle le déclarera pour elle seule —
et cette ligne-là méritera qu'on la remarque.

**Ce qu'il faut en retenir** : `SITE_URL` est figée au moment du build, comme
toute variable qui entre dans un rendu statique. La laisser à sa valeur de
développement en production donnerait un `sitemap.xml` rempli d'URLs `localhost`,
sans la moindre erreur au démarrage. Elle se déclare dans le
`.env.local.example` de l'application sur le poste, et se passera en
`build.args` en conteneur (INFRA-05), où le `.env` de la racine la porte sous le
nom `FRONTEND_INDIVIDUAL_SITE_URL`.

Ce qui n'y est **pas**, et pourquoi : ni image Open Graph (`opengraph-image`) ni
manifest — les deux réclament des visuels que le dépôt n'a pas encore, et une
carte de partage qui annonce une image absente est moins bonne qu'une carte
sobre ; pas de `lastModified` dans le sitemap non plus — la seule date
disponible aujourd'hui serait celle du build, qui changerait à chaque
déploiement sans que la page ait bougé. Annoncer une modification qui n'a pas eu
lieu est un signal que les moteurs finissent par ignorer.

## Le back-office de `frontend-admin`

À l'exact opposé de la précédente, `frontend-admin` est la seule des trois à être
**entièrement privée**. Elle applique le patron sans y toucher, et y ajoute
quatre choses.

**Rien n'est accessible sans session.** La règle est inversée par rapport à un
site ordinaire : ce n'est pas le contenu protégé qui se déclare, c'est le
contenu public, et il se réduit à la page de connexion. `proxy.ts` redirige
toute autre adresse vers `/login`, en conservant celle qui était demandée dans
un paramètre `next`.

:::warning Convention renommée par Next 16

**`proxy.ts`, et non `middleware.ts`.** Next 16 a renommé la convention.
L'ancien nom fonctionne encore mais fait avertir **chaque build** — le genre de
bruit permanent que FRONT-01 a refusé en désactivant `agentRules`. La fonction
exportée s'appelle donc `proxy` : c'est `mod.proxy` que Next cherche dans ce
fichier, et un export nommé `middleware` échouerait.

:::

Son `matcher` exclut quatre chemins. `login` d'abord, sans quoi la redirection se
redirigerait elle-même. **`robots.txt` ensuite, et c'est moins évident** : ce
fichier doit être servi, car un robot redirigé vers une page de connexion n'y
lit aucune directive — l'interdiction ci-dessous aurait été écrite pour
personne. Les fichiers statiques et les images optimisées ferment la liste : les
faire transiter coûterait une exécution par requête, pour rien.

**Aucune indexation.** Le bloc `robots` de `app/layout.tsx` est l'inverse de
celui de `frontend-individual`, au même endroit et dans le même ordre : comparer
les deux fichiers doit suffire à voir laquelle des applications est publique.
S'y ajoutent `nocache` et `noarchive`, qui interdisent de **conserver** une
copie — une page de back-office en cache public survivrait à sa dépublication.
Et `app/robots.ts` sert un `Disallow: /` complet, sans sitemap. Ces balises ne
protègent rien : elles s'adressent aux robots qui les respectent. Ce qui
protège, c'est le proxy et, en dernier ressort, l'API. Elles évitent l'accident,
pas l'attaque.

**Aucun rendu statique.** `export const dynamic = 'force-dynamic'` dans
`frontend/frontend-admin/app/(protected)/layout.tsx`, et là seulement — c'est la
**seule** directive de ce genre du dépôt, et la section précédente explique
pourquoi sa valeur tient à sa rareté. Elle est presque redondante, la lecture
d'un cookie suffisant déjà à rendre le segment dynamique ; elle est écrite quand
même, pour qu'aucune page de back-office ne finisse en HTML prérendu le jour où
l'une d'elles n'aura besoin d'aucune donnée de session. La page de connexion,
hors de ce groupe, ne la porte pas : elle n'affiche rien de confidentiel.

**Un shell de back-office.** Les groupes de routes découpent l'application en
deux : `(auth)` pour la connexion, nue, et `(protected)` pour tout le reste,
sous une barre latérale repliable, un fil d'Ariane et une zone de contenu.

| Fichier                                   | Rôle                                                                                                                  |
| ----------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `lib/session.ts`                          | Nom du cookie, type `Role`, lecture de la session. **Sans `next/headers`** : le proxy lit le cookie sur sa `request`. |
| `features/identity/require-role.ts`       | `getSession()` et la garde `requireRole('admin')` qu'appelle le layout protégé.                                       |
| `features/organization/clinics-table.tsx` | Le tableau des cliniques, seul écran métier de l'application à ce stade.                                              |
| `components/navigation.ts`                | Les sections du back-office, déclarées **une seule fois**.                                                            |
| `components/admin-sidebar.tsx`            | La navigation latérale, ses entrées filtrées par rôle.                                                                |
| `components/admin-breadcrumb.tsx`         | Le fil d'Ariane, dérivé du chemin.                                                                                    |

Le partage entre `lib/` et `features/identity/` n'est pas arbitraire, et ce n'est
pas nous qui l'avons choisi : `components/navigation.ts` lit le type `Role` pour
filtrer les entrées de la barre latérale, et le garde-fou de FRONT-09 interdit à
`components/` d'importer une feature. Le vocabulaire de session est donc
transverse à l'application ; la garde de rôle, elle, est du métier d'identité.
FRONT-07 fera monter le premier dans `@repo/api-client`.

Le fil d'Ariane n'est jamais renseigné page par page : il se déduit de
`usePathname()` et tire ses libellés de la même liste que la barre latérale.
Une page qui déclarerait elle-même sa position finirait par mentir après un
déplacement de route, et deux listes de libellés divergeraient au premier
renommage.

**Le contrôle d'accès par rôle est un confort d'affichage**, et le code le dit à
l'endroit où l'on serait tenté de croire l'inverse. Il évite d'afficher un écran
à qui n'a rien à y faire ; il ne protège aucune donnée. La vérification qui fait
foi est celle du backend — la fabrique `require_role(...)` de BACK-10, du côté où
la réponse est produite.

**Ce qui reste à FRONT-07.** Rien ici ne vérifie un jeton : `sessionFromToken`
constate la présence du cookie, sans lire sa signature ni son expiration. Le
service JWT est l'objet de BACK-10, son pendant navigateur celui de FRONT-07 —
qui déclare posséder `middleware.ts` et `app/(auth)/login/page.tsx`. Les chemins
posés ici sont donc les siens au caractère près, à la nuance de nom près
expliquée plus haut : il aura une fonction à compléter, pas une application à
re-router. La page de connexion n'a d'ailleurs pas de formulaire — en écrire un
sans API derrière aurait produit du code à jeter et un écran qui ment sur ce
qu'il sait faire.

### Voir le back-office aujourd'hui

Puisque rien n'émet encore de session, toute adresse redirige vers `/login`.
Pour traverser, poser le cookie à la main — sa **présence** suffit, sa valeur
n'est pas lue :

1. ouvrir [http://localhost:3003](http://localhost:3003) et attendre la page de
   connexion ;
2. dans les outils de développement, onglet **Application** (ou **Stockage**),
   section **Cookies**, ajouter sur `http://localhost:3003` un cookie nommé
   `juui_session`, valeur quelconque, chemin `/` ;
3. recharger.

Ou, plus court, depuis la console du navigateur :

```js
document.cookie = 'juui_session=demo; path=/';
```

Cette porte se referme d'elle-même avec FRONT-07, qui remplacera la lecture du
cookie par une vérification du jeton.

Les écarts assumés avec les tickets FRONT-01, FRONT-02 et FRONT-03 sont consignés au
[registre des écarts](../ecarts/front.md).
