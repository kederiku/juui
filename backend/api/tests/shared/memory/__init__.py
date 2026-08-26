"""Tests propres aux doublures en memoire (BACK-06c).

CE QUI EST ICI EST CE QUE LA CONFORMITE NE PEUT PAS COMPARER, et rien d'autre.
Trois familles :

- la REPONSE A LA PANNE, qui se simule d'un cote et demanderait d'arreter un
  conteneur de l'autre -- or c'est justement la moitie du contrat qu'on oublie
  de verifier : `Cache` degrade, `FileStorage` leve, `BreachChecker` accepte ;
- les GARDES PROPRES AU SOCLE en memoire : la copie qui coupe l'aliasing, la
  collision d'identifiant, l'oubli d'un attribut de classe ;
- les INSPECTEURS que les doublures ajoutent pour les tests -- `physical_keys`,
  `stored_content_type`, `commits` --, qui n'ont aucun equivalent reel.

Tout le reste appartient a `tests/shared/conformance/` : un comportement qui
peut se comparer aux deux implementations DOIT y etre, sinon il n'engage que la
doublure.

AUCUN MARQUEUR `conformance` ICI, ET C'EST LA MEME REGLE VUE DE L'AUTRE COTE.
`pyproject.toml` definit ce marqueur comme « suites jouees contre l'implementation
reelle ET sa doublure » : le poser sur ces tests ferait annoncer a
`pytest -m conformance` des tests qui ne comparent rien.
"""
