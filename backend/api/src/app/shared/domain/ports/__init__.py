"""Ports techniques du noyau partage -- les contrats, jamais leurs adaptateurs.

Un port est une classe abstraite qui exprime un BESOIN du metier ; l'adaptateur
qui le remplit vit dans `shared/infrastructure/`. Le domaine ne connait que le
port, ce qui laisse remplacer MinIO par Amazon S3, ou Redis par autre chose,
sans qu'une ligne de metier bouge.

Ces trois ports-la vivent dans `shared/` et non dans le domaine d'un module :
mettre `Cache` dans `identity` obligerait `medical_records` a importer
`identity` pour cacher une lecture -- exactement la dependance entre modules que
BACK-04 interdit.

CE QUE CHAQUE TICKET APPORTE ICI

| Fichier             | Port                          | Ticket   |
| ------------------- | ----------------------------- | -------- |
| `cache.py`          | `Cache`                       | BACK-14  |
| `file_storage.py`   | `FileStorage`                 | BACK-13  |
| `token_service.py`  | `TokenService`                | BACK-10a |
| `unit_of_work.py`   | `AbstractUnitOfWork`          | BACK-06a |
| `repository.py`     | protocole generique de depot  | BACK-06a |

Le paquet est vide a dessein : BACK-04 pose la place et le sens, chaque ticket
apporte son contrat. Le module pilote `identity` montre a quoi ressemble un port
en attendant -- le sien, `AccountRepository`, est METIER et vit donc dans son
propre domaine.
"""
