/**
 * Configuration de lint-staged (SETUP-04).
 *
 * lint-staged ne voit que les fichiers INDEXES du commit en cours : c'est ce qui
 * tient le hook sous les 10 s exigees par le ticket, la ou un `pnpm lint` nu
 * reparcourrait tout le depot a chaque commit.
 *
 * Trois comportements a connaitre avant de toucher a ce fichier :
 *
 * 1. Les chemins passes aux commandes sont ABSOLUS -- c'est le defaut, et c'est
 *    ce qu'anticipait deja le `src = ["src"]` de backend/api/pyproject.toml.
 *    Une commande n'a donc pas a se soucier du repertoire depuis lequel elle est
 *    lancee (la racine du depot, ou git place ses hooks).
 * 2. Il n'y a PLUS DE SHELL depuis lint-staged 16 : chaque chaine est une
 *    commande unique suivie de ses arguments, jamais une ligne de shell. Ni
 *    `&&`, ni redirection, ni glob a developper -- d'ou deux entrees distinctes
 *    pour Ruff.
 * 3. Un tableau plat s'execute EN SEQUENCE, dans l'ordre ecrit ; c'est un
 *    tableau imbrique qui declencherait un lancement en parallele. Les fichiers
 *    reecrits par une tache sont re-indexes tout seuls, si bien qu'un formatage
 *    automatique entre dans le commit qui l'a declenche.
 *
 * @type {import('lint-staged').Configuration}
 */
export default {
  // ESLint d'abord, Prettier ensuite : la mise en forme a le dernier mot.
  // eslint-config-prettier (SETUP-03) garantit qu'ils ne se contredisent jamais.
  //
  // Le ticket ne citait que `ts,tsx,js,jsx` ; `mjs` et `cjs` sont ajoutes parce
  // que les fichiers de configuration du depot -- a commencer par celui-ci --
  // sont precisement en .mjs. Sans eux, le hook ne couvrirait pas ses propres
  // sources.
  //
  // `--no-warn-ignored` : ESLint avertit quand un fichier qu'on lui passe
  // nommement est exclu par sa configuration (`backend/**`, `**/generated/**`,
  // `**/dist/**`...). Sans ce drapeau, tout commit touchant un tel fichier
  // afficherait un avertissement sans objet.
  '*.{ts,tsx,js,jsx,mjs,cjs}': ['eslint --fix --no-warn-ignored', 'prettier --write'],

  // Prettier saute silencieusement ce que .prettierignore exclut -- pnpm-lock.yaml
  // au premier chef -- meme quand le fichier lui est passe nommement.
  '*.{json,md,yaml,yml}': ['prettier --write'],

  // Volet Python, outille par Ruff en BACK-02.
  //
  // `--project backend/api` fait decouvrir a uv le projet et son .venv sans
  // changer le repertoire de travail : les chemins absolus recus restent
  // valides. Ruff, de son cote, remonte l'arborescence depuis chaque fichier et
  // trouve seul backend/api/pyproject.toml.
  //
  // L'ordre est celui qu'impose le ticket : corriger ce qui peut l'etre, puis
  // formater. Ce qui reste non corrigeable fait echouer `ruff check`, donc le
  // commit.
  //
  // Prerequis : `uv` sur le poste. Qui n'indexe jamais de Python ne declenche
  // jamais cette entree, et n'en a donc pas besoin.
  'backend/**/*.py': [
    'uv run --project backend/api ruff check --fix',
    'uv run --project backend/api ruff format',
  ],
};
