"""Adaptateurs des ports techniques vers les services externes.

Ce que BACK-04 avait reserve ici : les clients des services que le domaine ne
connait que par un port. Chacun suit la meme forme que le socle de persistance
(BACK-05) -- une fabrique qui recoit `Settings` en argument, une ressource rangee
dans `app.state` par le `lifespan`, un accesseur qui la rend.

CE QUE CHAQUE TICKET APPORTE ICI

| Fichier          | Port          | Ticket   |
| ---------------- | ------------- | -------- |
| `cache_keys.py`  | --            | BACK-14  |
| `redis_cache.py` | `Cache`       | BACK-14  |
| `s3_storage.py`  | `FileStorage` | BACK-13  |

`cache_keys.py` ne remplit aucun port : il porte la convention de nommage des
cles, partagee par l'adaptateur Redis et par toute doublure du port. L'enfermer
dans `redis_cache.py` obligerait une doublure en memoire a importer le client
Redis pour savoir nommer une cle.
"""
