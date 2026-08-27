"""Adaptateurs des ports techniques vers les services externes.

Ce que BACK-04 avait reserve ici : les clients des services que le domaine ne
connait que par un port. Chacun suit la meme forme que le socle de persistance
(BACK-05) -- une fabrique qui recoit `Settings` en argument, une ressource rangee
dans `app.state` par le `lifespan`, un accesseur qui la rend.

CE QUE CHAQUE TICKET APPORTE ICI

| Fichier           | Port             | Ticket   |
| ----------------- | ---------------- | -------- |
| `cache_keys.py`   | --               | BACK-14  |
| `redis_cache.py`  | `Cache`          | BACK-14  |
| `storage_keys.py` | --               | BACK-13  |
| `s3_storage.py`   | `FileStorage`    | BACK-13  |
| `smtp_mailer.py`  | `EmailTransport` | BACK-22  |
| `hibp.py`         | `BreachChecker`  | BACK-10b |

`cache_keys.py` et `storage_keys.py` ne remplissent aucun port : ils portent les
conventions de nommage, partagees par l'adaptateur et par toute doublure du port
correspondant. Les enfermer dans l'adaptateur obligerait une doublure en memoire
a importer le client Redis, ou boto3, pour savoir nommer une cle.

LES DEUX CONVENTIONS NE SE RESSEMBLENT PAS, ET C'EST LE POINT
Une cle de cache est VOLATILE : l'adaptateur y appose l'environnement et le
groupe actif, ce qui rend le cloisonnement structurel. Une cle de stockage est
PERSISTEE en base : elle ne porte ni l'un ni l'autre, faute de quoi elle
deviendrait introuvable des que le contexte de lecture differe de celui de
l'ecriture. Copier la premiere pour ecrire la troisieme serait une erreur --
c'est la duree de vie de la cle qui decide, pas le style du fichier voisin.

`smtp_mailer.py` ET `hibp.py` NE SUIVENT PAS LA FORME DES TROIS AUTRES
Leurs fabriques recoivent bien `Settings`, mais rien ne se range dans `app.state`
et aucun accesseur ne le rend : une session SMTP nait et meurt avec chaque
message, un client HTTP aussi. Il n'y a donc ni ressource a ouvrir au demarrage
ni ressource a refermer a l'arret. Ce qui varie d'un adaptateur a l'autre n'est
pas le style, c'est ce qu'il detient entre deux appels.

Pour `hibp.py` (BACK-10b), la question meritait d'etre posee -- un client HTTP
partage economiserait une poignee de main TLS par appel -- et sa docstring dit
sur quoi elle a ete tranchee. Corollaire utile a connaitre d'ici : une fabrique
autonome sert le semis d'INFRA-08 sans qu'un script ait a construire une
application FastAPI.
"""
