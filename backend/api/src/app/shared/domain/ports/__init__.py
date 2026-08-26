"""Ports techniques du noyau partage -- les contrats, jamais leurs adaptateurs.

Un port est une classe abstraite qui exprime un BESOIN du metier ; l'adaptateur
qui le remplit vit dans `shared/infrastructure/`. Le domaine ne connait que le
port, ce qui laisse remplacer MinIO par Amazon S3, ou Redis par autre chose,
sans qu'une ligne de metier bouge.

Ces ports-la vivent dans `shared/` et non dans le domaine d'un module :
mettre `Cache` dans `identity` obligerait `medical_records` a importer
`identity` pour cacher une lecture -- exactement la dependance entre modules que
BACK-04 interdit.

CE QUE CHAQUE TICKET APPORTE ICI

| Fichier             | Port                                | Ticket   |
| ------------------- | ----------------------------------- | -------- |
| `cache.py`          | `Cache`                             | BACK-14  |
| `email.py`          | `EmailTransport`                    | BACK-22  |
| `file_storage.py`   | `FileStorage`                       | BACK-13  |
| `token_service.py`  | `TokenService`                      | BACK-10a |
| `unit_of_work.py`   | `AbstractUnitOfWork`                | BACK-06a |
| `repository.py`     | `Repository` (protocole generique)  | BACK-06a |

BACK-04 a pose la place et le sens, chaque ticket apporte son contrat. Cinq
sont livres -- `cache.py` par BACK-14, `email.py` par BACK-22, `file_storage.py`
par BACK-13, `unit_of_work.py` et `repository.py` par BACK-06a ; seul
`token_service.py` reste une place reservee.

`email.py` EST LE CAS LIMITE QUI VALIDE LA REGLE. Le transport de courriel
appartenait a `notifications` par sa carte, et il est ici parce qu'`identity`
en a besoin sans avoir le droit d'importer ce module : un besoin technique que
DEUX modules atteignent devient un port de `shared/`, sinon le premier arrive
devient une dependance du second (ADR-0022). Le module pilote `identity` montre les ports METIER,
les siens -- `AccountRepository` et `IdentityUnitOfWork` vivent dans son propre
domaine, et non ici.

CE QUE LES PORTS ONT ETABLI EN S'OPPOSANT
Ils se ressemblent de loin et se comportent chacun a sa facon devant une panne,
et c'est la question a se poser en ecrivant le prochain : `Cache` DEGRADE,
parce qu'un cache absent ne change qu'une latence ; `FileStorage` LEVE, parce
qu'un stockage absent change les resultats -- un upload silencieux est un
fichier perdu ; `EmailTransport` LEVE pour la meme raison, un message perdu en
silence etant un message dont personne n'apprendra jamais l'absence ;
`AbstractUnitOfWork` LEVE ET ANNULE -- un commit en echec remonte, une sortie de
bloc sans commit n'ecrit rien. Un port ne se contente
donc pas de nommer des operations : il dit ce qui se passe quand le service
qu'il masque ne repond plus, et cette reponse ne s'herite pas du port
precedent.

CE QUE `cache.py` A ETABLI, ET QUE LES SUIVANTS REPRENDRONT
Un port est une `ABC` aux methodes asynchrones, ecrit en bibliotheque standard
SEULE. La contrainte n'est pas de style : le contrat `domain-purity` de BACK-04b
refuse aussi les chaines INDIRECTES, donc un port ne peut pas non plus importer
`app.core` -- qui importe pydantic. Un port ne lit donc jamais la configuration,
et tout ce qui en depend appartient a l'adaptateur.
"""
