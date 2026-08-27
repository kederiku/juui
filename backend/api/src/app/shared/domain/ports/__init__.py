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

| Fichier              | Port                                | Ticket   |
| -------------------- | ----------------------------------- | -------- |
| `breach_checker.py`  | `BreachChecker`                     | BACK-06c |
| `cache.py`           | `Cache`                             | BACK-14  |
| `email.py`           | `EmailTransport`                    | BACK-22  |
| `file_storage.py`    | `FileStorage`                       | BACK-13  |
| `password_hasher.py` | `PasswordHasher`                    | BACK-10b |
| `token_service.py`   | `TokenService`                      | BACK-10a |
| `unit_of_work.py`    | `AbstractUnitOfWork`                | BACK-06a |
| `repository.py`      | `Repository` (protocole generique)  | BACK-06a |

BACK-04 a pose la place et le sens, chaque ticket apporte son contrat. Les sept
que BACK-04 avait prevus sont livres ; `password_hasher.py` est le HUITIEME, et
il est ne exactement comme la phrase ci-dessous l'annoncait -- d'un besoin, et
non d'un emplacement reserve. Ce besoin est celui de BACK-10b : hacher un mot de
passe sans qu'`argon2` entre dans le domaine, et nommer d'un seul endroit ce qui
se passe quand une empreinte est illisible.

`breach_checker.py` ETAIT LE SECOND CAS LIMITE, ET IL A CESSE DE L'ETRE. Son
adaptateur est livre par BACK-10b, comme annonce. Ce qui reste vrai est la regle
que ce cas avait servi a poser : ecrire un port sans son adaptateur est
l'exception, et elle se justifie par un ticket ANTERIEUR qui en a besoin -- ici,
la doublure `FakeBreachChecker` de BACK-06c, qui repond a un contrat et n'en
invente pas un.

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
bloc sans commit n'ecrit rien ; `BreachChecker` DEGRADE, mais pour un motif qui
n'est PAS celui du cache -- refuser une inscription parce qu'un service tiers est
muet coute plus cher que le risque couvert. Un port ne se contente
donc pas de nommer des operations : il dit ce qui se passe quand le service
qu'il masque ne repond plus, et cette reponse ne s'herite pas du port
precedent -- deux ports qui degradent peuvent le faire pour des raisons sans
rapport. `TokenService` LEVE ET N'EMET RIEN, ce qui etait la reponse la plus
severe des sept, et pour le motif le plus simple : un jeton emis sans que
l'appartenance ait pu etre verifiee est une elevation de privilege qui vivra
jusqu'a son expiration, sans que personne apprenne qu'elle a eu lieu.
`PasswordHasher` LEVE lui aussi, et il donne au passage la meilleure
illustration de la regle : livre par le MEME ticket que `breach_checker.py`, dans
le meme parcours, il repond a l'inverse de son voisin. Ce n'est pas une
inconsequence, et sa docstring deroule le raisonnement plutot que de le repeter
ici.

CE QUE `cache.py` A ETABLI, ET QUE LES SUIVANTS REPRENDRONT
Un port est une `ABC` aux methodes asynchrones, ecrit en bibliotheque standard
SEULE. La contrainte n'est pas de style : le contrat `domain-purity` de BACK-04b
refuse aussi les chaines INDIRECTES, donc un port ne peut pas non plus importer
`app.core` -- qui importe pydantic. Un port ne lit donc jamais la configuration,
et tout ce qui en depend appartient a l'adaptateur.
"""
