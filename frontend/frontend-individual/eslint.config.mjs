import next from '@repo/eslint-config/next';
import { defineConfig, globalIgnores } from 'eslint/config';

/**
 * Configuration ESLint de frontend-individual (FRONT-02).
 *
 * Preset `next`, comme frontend-professional : le socle `base`, les regles de
 * hooks de `react`, et les 22 regles de `@next/eslint-plugin-next` en variante
 * core-web-vitals.
 *
 * `.next/**` est re-exclu ici bien que la configuration de la racine l'exclue
 * deja : depuis ESLint 10 la recherche part du repertoire du fichier analyse, si
 * bien que ce fichier REMPLACE celui de la racine pour ce workspace -- ses
 * exclusions comprises.
 */
export default defineConfig([globalIgnores(['.next/**']), ...next]);
