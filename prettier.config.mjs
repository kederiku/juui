// Source de verite : packages/config-prettier (`@repo/prettier-config`).
//
// Prettier resout sa configuration en remontant l'arborescence depuis chaque
// fichier formate : ce fichier a la racine couvre donc tout le monorepo. Une
// application qui aurait besoin d'une surcharge locale posera son propre
// prettier.config.mjs, en repartant de ce meme package.
export { default } from '@repo/prettier-config';
