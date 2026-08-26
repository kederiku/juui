"""Suites de conformite : la meme suite, jouee contre le reel et contre la doublure (BACK-06c).

C'EST LE QUATRIEME CRITERE DU TICKET, ET LE SEUL MECANISME QUI TIENNE DANS LE TEMPS
Une doublure ecrite avec soin est fidele le jour ou elle est ecrite. Ce qui la
fait DIVERGER, c'est le ticket suivant : une regle ajoutee a l'adaptateur reel et
oubliee dans la doublure, ou l'inverse. Rien dans le code ne peut empecher cela
-- seule une suite qui s'execute deux fois le peut, en refusant de passer des
deux cotes tant que les deux ne se comportent pas pareil.

LA FORME : UNE CLASSE DE BASE, DEUX SOUS-CLASSES
La classe de base porte les tests et ne fournit rien ; chaque sous-classe ne
fournit que la fixture du SUJET. Elle ne s'appelle pas `Test...`, donc pytest ne
la collecte pas -- les tests ne tournent que par les sous-classes, et un test
ajoute a la base est mecaniquement joue des deux cotes. C'est le point : on ne
peut pas ajouter un test a une seule moitie sans le voir.

LES MOITIES REELLES SONT IGNOREES QUAND LEUR SERVICE NE REPOND PAS
PostgreSQL, Redis et MinIO tournent par `make dev`. Sans eux, la moitie reelle
est `skip` avec le message qui dit quoi lancer, et la moitie en memoire passe
seule. Une suite verte n'est donc PAS la preuve que la conformite a ete
verifiee : lire les `skip` du rapport. C'est le meme parti que
`test_redis_otp_store.py`, et la meme discipline -- aucun `FLUSHDB`, aucune cle
fixe, des identifiants tires au hasard a chaque test.
"""
