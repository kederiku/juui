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

LES MOITIES REDIS ET MINIO SONT IGNOREES QUAND LEUR SERVICE NE REPOND PAS
`make dev` les demarre. Sans eux, ces moities-la sont `skip` avec le message qui
dit quoi lancer, et le reste passe. Une suite verte n'est donc PAS la preuve que
la conformite a ete verifiee : lire les `skip` du rapport. C'est le parti de
`test_redis_otp_store.py`, et la meme discipline -- aucun `FLUSHDB`, aucune cle
fixe, des identifiants tires au hasard a chaque test.

POSTGRESQL, LUI, NE SE SAUTE PAS : IL ARRETE LA SESSION ENTIERE
La fixture `engine` du conftest racine appelle `pytest.exit()` quand la base de
test ne repond pas -- choix de BACK-06b, pour que la preuve d'isolation ne puisse
pas etre sautee en silence. La consequence traverse ce ticket : sans PostgreSQL,
la suite s'arrete, et les moities EN MEMOIRE ne tournent pas davantage, alors
qu'elles n'ont besoin de rien. C'est un ecart, il est consigne, et l'arbitrage
appartient a BACK-12 qui reprend le harnais -- pas a un ticket de doublures.
"""
