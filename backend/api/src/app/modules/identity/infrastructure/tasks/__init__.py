"""Taches de fond du module identity (BACK-17).

LE SOUS-PAQUET QUE `discovery.py` CHERCHE, ET SON IMPORT EST UN EFFET RECHERCHE
Au demarrage du worker, `shared/infrastructure/tasks/discovery.py` importe
`app.modules.<module>.infrastructure.tasks` partout ou ce sous-paquet existe :
c'est cet import qui enregistre les taches decorees `@broker.task` aupres du
broker deja construit. `identity` est le PREMIER module a en avoir un, et le
mecanisme de BACK-15 s'applique tel quel -- ni Dockerfile ni compose a toucher.

Sans la ligne d'import ci-dessous, le sous-paquet s'importerait sans rien
enregistrer : le worker demarrerait, les taches partiraient en file, et personne
ne viendrait jamais les consommer. Meme geste, et meme raison, que l'import de
`demo` dans le `__init__` de `shared/infrastructure/tasks/`.
"""

from app.modules.identity.infrastructure.tasks import otp  # noqa: F401
from app.modules.identity.infrastructure.tasks.otp import (
    TaskOtpDispatcher,
    send_email_verification_otp,
)

__all__ = ["TaskOtpDispatcher", "send_email_verification_otp"]
