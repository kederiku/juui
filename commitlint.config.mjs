/**
 * Convention de message de commit (SETUP-04).
 *
 * Socle : @commitlint/config-conventional, c'est-a-dire la specification
 * Conventional Commits -- `type(scope facultatif): sujet`. Les deux reglages
 * ci-dessous sont les seuls ecarts ; tout le reste est HERITE et volontairement
 * non recopie : en-tete de 100 caracteres au plus, type en minuscules, sujet non
 * vide, sans point final et hors sentence/start/pascal/upper-case, corps et pied
 * de page a 100 caracteres par ligne.
 *
 * Les messages de merge, de revert, de fixup et de squash sont ignores d'office
 * par commitlint : un `git merge` local ne sera pas rejete.
 */
export default {
  extends: ['@commitlint/config-conventional'],

  rules: {
    // Les huit types du ticket. Le socle conventionnel en autorise onze : on
    // retire `perf`, `revert` et `style`. Ce dernier n'a de toute facon plus
    // d'objet ici -- Prettier et Ruff formatent tout seuls, personne n'aura a
    // commiter « du style ».
    'type-enum': [2, 'always', ['feat', 'fix', 'chore', 'docs', 'refactor', 'test', 'ci', 'build']],

    // Le scope reste FACULTATIF : cette regle ne se prononce que sur les
    // messages qui en portent un. Elle interdit donc les scopes fantaisistes
    // (`front`, `frontend-admin`, une faute de frappe), pas leur absence.
    //
    // La liste suit les workspaces REELS, pas une nomenclature figee. Regle a
    // tenir : un nouveau workspace ajoute son scope ici, dans la PR qui le cree
    // -- `api-client` en SHARED-03, `config-typescript` et `config-tailwind` en
    // SHARED-02.
    'scope-enum': [
      2,
      'always',
      [
        'api', // backend/api
        'professional', // frontend/frontend-professional
        'individual', // frontend/frontend-individual
        'admin', // frontend/frontend-admin
        'ui', // packages/ui (SHARED-01)
        'docker', // docker/
        'documentation', // documentation/ (DOC-01)
      ],
    ],
  },
};
