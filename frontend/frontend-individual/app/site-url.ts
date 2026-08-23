/**
 * URL canonique publique de frontend-individual (FRONT-02).
 *
 * POURQUOI UN FICHIER POUR UNE CHAINE
 * Trois fichiers doivent s'accorder sur cette adresse -- le `metadataBase` du
 * layout, le renvoi vers le sitemap dans `robots.ts`, et chaque entree de
 * `sitemap.ts`. Trois copies divergeraient au premier changement de domaine, et
 * la divergence serait SILENCIEUSE : un sitemap annoncant un autre hote que les
 * balises canoniques ne casse rien, il se contente d'etre ignore.
 *
 * C'est la seule des trois applications a en avoir besoin : les deux autres ne
 * sont pas indexables, donc n'ont pas d'URL canonique a declarer.
 *
 * Valeur lue dans `SITE_URL`, sans prefixe `NEXT_PUBLIC_` a dessein : les trois
 * consommateurs ci-dessus tournent au build ou sur le serveur, jamais dans le
 * navigateur -- meme raisonnement que pour `API_INTERNAL_URL`.
 *
 * A SAVOIR : les pages, le sitemap et le robots.txt etant prerendus, la valeur
 * est figee au BUILD. La changer suppose de reconstruire ; en conteneur
 * (INFRA-05) elle se passe en `build.args`, pas en variable d'execution.
 *
 * Le repli vaut le port de developpement de l'application. Il ne sert qu'au
 * poste : en production, une absence de `SITE_URL` produirait des URLs
 * `localhost` dans le sitemap -- d'ou la mention explicite dans
 * `.env.local.example` et dans le `.env.example` de la racine.
 */

// La barre oblique finale est retiree une fois pour toutes : le reste du code
// compose des `${SITE_URL}/...`, et `https://juui.fr//sitemap.xml` serait une
// URL differente aux yeux d'un moteur.
export const SITE_URL = (process.env.SITE_URL ?? 'http://localhost:3002').replace(/\/+$/, '');
