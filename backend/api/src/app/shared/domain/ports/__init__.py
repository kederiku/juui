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

BACK-04 a pose la place et le sens, chaque ticket apporte son contrat. BACK-14 a
livre le premier, `cache.py` ; les quatre autres lignes du tableau restent des
places reservees. Le module pilote `identity` montre un port METIER, le sien --
`AccountRepository` vit dans son propre domaine, et non ici.

CE QUE `cache.py` A ETABLI, ET QUE LES SUIVANTS REPRENDRONT
Un port est une `ABC` aux methodes asynchrones, ecrit en bibliotheque standard
SEULE. La contrainte n'est pas de style : le contrat `domain-purity` de BACK-04b
refuse aussi les chaines INDIRECTES, donc un port ne peut pas non plus importer
`app.core` -- qui importe pydantic. Un port ne lit donc jamais la configuration,
et tout ce qui en depend appartient a l'adaptateur.
"""
