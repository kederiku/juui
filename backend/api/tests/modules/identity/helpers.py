"""Aides des tests d'identity : fabriques de donnees et lecture de l'etat valide (BACK-06c).

CE QUI RESTE SOUS `tests/` QUAND LES DOUBLURES PARTENT DANS `src/`
Une doublure repond a un PORT : elle a un contrat a tenir, et sa place est a cote
des autres implementations de ce contrat. Ce qui suit ne repond a personne --
deux fabriques qui abregent l'ecriture d'un test, et une lecture d'assertion --
et n'a aucun equivalent en production. C'est la ligne que BACK-06c trace en
deplacant `otp_doubles.py` : les classes sont parties, ces trois fonctions sont
restees.

Le module ne porte pas le prefixe `test_` : pytest ne le collecte pas.
"""

from uuid import UUID

from app.modules.identity.domain.entities import Account, AccountType
from app.modules.identity.domain.policies import OtpRules
from app.modules.identity.infrastructure.memory.unit_of_work import (
    InMemoryIdentityUnitOfWork,
)

# Bornes par defaut des tests -- celles du gabarit .env.example. Chaque test
# surcharge ce dont il a besoin, et rien d'autre : un test qui ecrit ses six
# valeurs ne dit plus laquelle il eprouve.
_DEFAULT_RULES = {
    "ttl_seconds": 600,
    "max_attempts": 3,
    "resend_min_interval_seconds": 60,
    "resend_window_seconds": 3600,
    "resend_max_per_email": 5,
    "resend_max_per_ip": 20,
}


def otp_rules(**overrides: int) -> OtpRules:
    """Un jeu de bornes complet, surchargeable champ par champ."""
    return OtpRules(**{**_DEFAULT_RULES, **overrides})


def an_account(*, email: str = "jean@exemple.fr", verified: bool = False) -> Account:
    """Un compte particulier, verifie ou non.

    Passe par `Account.create()` puis bascule l'etat par le COMPORTEMENT de
    l'entite : construire directement une dataclass avec `email_verified=True`
    contournerait l'invariant, et un test qui contourne l'invariant ne teste plus
    le meme objet que la production.
    """
    account = Account.create(
        email=email,
        first_name="Jean",
        last_name="Veto",
        account_type=AccountType.INDIVIDUAL,
    )
    if verified:
        account.verify_email()
    return account


def stored_account(uow: InMemoryIdentityUnitOfWork, account_id: UUID) -> Account:
    """Relit l'etat VALIDE d'un compte, hors de tout bloc.

    C'est ce qu'un test interroge pour assurer qu'une ecriture a bien ete
    COMMITEE : `uow.accounts` refuserait de repondre hors bloc, et c'est
    justement ce qu'on veut lui faire dire par ailleurs. La forme generique
    (`committed_entity`) rend `None` quand rien n'est valide -- utile pour
    prouver une absence, penible a enchainer sur un attribut, d'ou cette
    lecture qui echoue en le disant.

    Args:
        uow: l'unite de travail en memoire du test.
        account_id: le compte cherche.

    Returns:
        Le compte, tel qu'il a ete commite.

    Raises:
        AssertionError: si aucun compte valide ne porte cet identifiant.
    """
    account = uow.accounts_store.committed_entity(account_id)
    assert account is not None, f"Aucun compte valide ne porte l'identifiant {account_id}."
    return account
