# Arborescence de demonstration des frontieres de features (FRONT-09)

Ces fichiers ne sont pas du code applicatif : ils sont la **cible** des imports que
`scripts/verify-boundaries.js` joue contre le generateur de zones de `boundaries.js`.

Ils existent pour une raison precise. `import-x/no-restricted-paths` ne se declenche que si
l'import qu'elle examine **se resout reellement sur le disque** : sans fichier a viser, une
violation ne serait pas signalee, et un controle qui ne peut pas echouer ne prouve rien.

Les trois familles de zones se verifient donc ainsi :

| Famille                                    | Ou elle est prouvee                                                    |
| ------------------------------------------ | ---------------------------------------------------------------------- |
| 1. L'interieur d'une feature est prive     | **Ici** — aucune feature reelle n'a encore de sous-dossier a proteger. |
| 2. Le transverse ne connait aucune feature | Sur le vrai depot, avec la configuration reelle des applications.      |
| 3. Personne ne remonte vers `app/`         | Sur le vrai depot, avec la configuration reelle des applications.      |

L'arborescence reproduit celle qu'attend `boundaries.js` — `frontend/<application>/app/` designe
une application, `frontend/<application>/features/<sujet>/` une feature — et rien de plus.

Ces fichiers ne sont **pas** exclus du lint du depot, et c'est deliberé : ce sont du TypeScript
ordinaire et valide, qui passe le socle comme n'importe quel autre fichier. Les violations, elles,
ne sont jamais ecrites sur le disque -- le programme de verification les joue en memoire, avec
`lintText`, sur ces chemins-la. Les fixtures ne peuvent donc pas pourrir sans que `pnpm lint` le
dise.
