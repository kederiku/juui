"""Le harnais de la suite : ce qui aide a tester, et qui n'est pas un test.

POURQUOI UN PAQUET A PART, ET PAS `tests/shared/` (BACK-12)
`tests/shared/` miroite `src/app/shared/` : ce qu'on y trouve TESTE le noyau
partage. Les sondes HTTP, les doublures d'authentification, la fabrique de
jetons et les stubs de tenance ne testent rien du tout -- ils servent a tester
autre chose. Les laisser dans `tests/shared/` faisait mentir le miroir, et
c'etait la source de la confusion que ce ticket avait a lever.

La regle qui en decoule tient en une phrase : un module de `tests/support/` ne
commence pas par `test_`, n'est donc pas collecte, et ne contient AUCUNE
assertion sur le service. Ce qui repond a un port va dans `src/` (ADR-0023) ;
ce qui ne repond a personne vit ici.
"""
