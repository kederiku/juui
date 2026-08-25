"""Taches de fond du service : broker TaskIQ, cycle de vie, patron de reference.

Ce paquet porte l'EXECUTION DIFFEREE : ce qu'une requete HTTP ne doit pas
attendre -- envoi d'e-mails, generation de PDF, traitement d'images -- part
dans une file Redis (base 1) et s'execute dans le processus worker, un service
distinct du meme code (INFRA-05b).

Ce que chaque ticket apporte ici :

| Ticket  | Contenu |
| ------- | ------- |
| BACK-15 | `broker.py` (chemin fige par la CLI du worker), `middlewares.py`   |
|         | (correlation, reprise, rejets), `lifecycle.py` (ressources du      |
|         | worker), `discovery.py` (taches des modules), `demo.py` (le patron) |
| BACK-17 | consommateur : codes OTP, via `identity/infrastructure/tasks/`     |
| BACK-22 | consommateur : notifications, via un sous-paquet de meme forme     |

LA REGLE QUI ENGAGE TOUTE TACHE : DES IDENTIFIANTS SERIALISABLES, JAMAIS D'ORM
Une tache recoit des identifiants (`UUID`, `str`, nombres), JAMAIS une entite ni
un modele SQLAlchemy. Interdit : `await send_welcome.kiq(account)`. Attendu :
`await send_welcome.kiq(group_id=account.group_id, account_id=account.id)`, et
la tache RECHARGE l'agregat par son identifiant, dans sa propre unite de
travail construite depuis `get_task_database` -- jamais `get_identity_uow`, qui
suppose une requete HTTP. Trois raisons, chacune suffisante : un objet ORM est
detache de sa session et ses acces paresseux levent ; son etat date du `kiq` et
peut etre perime a l'execution ; le fil transporte du JSON, ce qui ne s'y
serialise pas ne part pas.

ET LE GROUPE NE TRAVERSE PAS LA FILE TOUT SEUL : toute tache liee a un tenant
prend `group_id` en premier argument et ouvre son corps par
`with use_group(group_id):` -- le patron est `demo.record_ping`, l'argumentaire
est l'ADR-0008.
"""

# L'import de `demo` est un EFFET RECHERCHE : c'est lui qui enregistre les
# taches de `shared/` aupres du broker. La CLI du worker importe
# `...tasks.broker`, ce qui execute d'abord ce `__init__` -- les taches des
# MODULES, elles, arrivent par `discovery.py` au demarrage du worker.
from app.shared.infrastructure.tasks import demo  # noqa: F401
from app.shared.infrastructure.tasks.broker import broker

__all__ = ["broker"]
