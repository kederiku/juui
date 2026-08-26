"""Contexte de requete : ce qui a declenche le traitement en cours (BACK-15, BACK-11).

Une tache de fond s'execute dans un autre processus que la requete HTTP qui l'a
demandee. Pour relire un incident de bout en bout -- « cet e-mail n'est jamais
parti » --, il faut pouvoir suivre l'identifiant de la requete d'origine jusque
dans les journaux du worker. « Quelle requete a demande ce traitement ? » n'est
pas une propriete du code appele mais de l'appel : une `ContextVar`, comme le
groupe actif de `tenancy.py`.

TROIS VARIABLES, UN SEUL MOTIF
Aux cotes de l'identifiant de requete, ce module porte le COMPTE et la CLINIQUE
du traitement en cours (BACK-11). Toutes trois repondent a la meme question --
« au nom de qui, et sur quel perimetre ? » -- et toutes trois sont posees par la
bordure HTTP, jamais a la main par un cas d'usage. `core/logging.py` les lit
pour enrichir chaque ligne de journal, ce qui rend un incident multi-tenant
diagnosticable apres coup.

LE GROUPE ACTIF N'EST PAS ICI, ET C'EST DELIBERE
`current_group_id` vit dans `shared/infrastructure/tenancy.py` : c'est la
frontiere d'ISOLATION, lue par la persistance et par le cache, et elle porte
trois etats la ou celles-ci n'en ont que deux. La recopier ici ferait deux
sources de verite a tenir synchrones. `core/logging.py` la recoit donc par
injection -- `configure_logging(..., context_providers=...)` --, depuis les
points d'entree du processus qui, eux, ont le droit de connaitre `shared`.

POURQUOI DANS `core/` ET NON DANS `shared/`
`core/logging.py` (BACK-11) lit ces contextvars pour enrichir chaque ligne de
journal, et le contrat `service-spaces` interdit a `core` d'importer `shared`.
Les intergiciels -- HTTP (BACK-11) comme TaskIQ (BACK-15) -- vivent en
`shared/infrastructure/` et peuvent importer `core` : la fleche pointe dans le
bon sens.

UNE `str` OPAQUE POUR LA REQUETE, DES `UUID` POUR LE RESTE
L'identifiant de requete est un jeton de correlation, pas une cle metier : il se
compare, il ne se decompose pas -- et il peut venir d'un client, d'une
passerelle ou d'un autre service, qui n'ont aucune raison d'emettre un UUID. Le
compte et la clinique, eux, sont des identifiants de NOTRE domaine : les typer
`UUID` fait echouer une valeur malformee a la bordure qui la pose (BACK-10c),
et non trois couches plus loin -- ou, pire, seulement dans les journaux.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Final
from uuid import UUID

# Identifiant de la requete d'origine, ou `None` hors de tout contexte de
# correlation.
#
# `default=None` et non l'absence de defaut, pour la raison ecrite sur
# `current_group_id` : un traitement sans requete d'origine -- une sonde, un
# script -- est un etat NORMAL, pas une erreur a lever. Les deux contextvars
# ci-dessous suivent la meme regle.
current_request_id: Final[ContextVar[str | None]] = ContextVar("current_request_id", default=None)

# Seconde demeure de l'identifiant de requete : le `scope` ASGI.
#
# POURQUOI DEUX, ALORS QU'UNE CONTEXTVAR SUFFIRAIT PRESQUE
# `ServerErrorMiddleware` de Starlette est la couche la PLUS EXTERIEURE : quand
# une exception imprevue remonte, il construit sa reponse 500 apres que
# l'intergiciel de correlation a rendu la main, donc apres le `reset(token)`.
# La contextvar y vaut de nouveau `None`, et le corps du 500 sortirait sans
# identifiant -- precisement la reponse ou l'on en a le plus besoin. Le `scope`,
# lui, vit aussi longtemps que la requete : le handler du 500 y lit la valeur
# sans que personne ait a fausser la duree de vie de la contextvar.
#
# Le prefixe `juui.` suit la convention ASGI des cles d'extension : le `scope`
# est partage avec le serveur et avec toute bibliotheque de la chaine.
REQUEST_ID_SCOPE_KEY: Final = "juui.request_id"

# En-tete par lequel l'identifiant entre et ressort, en minuscules --
# `Headers` de Starlette indexe ainsi. Il vit ICI et non dans les
# intergiciels parce qu'il a DEUX ecrivains : l'intergiciel de correlation
# sur les reponses ordinaires, et le handler du 500 (BACK-09) sur celles qui
# echappent a la pile d'intergiciels.
REQUEST_ID_HEADER: Final = "x-request-id"

# Compte authentifie au nom duquel le traitement s'execute, ou `None`.
#
# `None` est l'etat d'une route publique -- inscription, connexion, sonde de
# sante -- et d'une tache de fond declenchee par l'ordonnanceur. Rien ici ne
# tient lieu d'autorisation : c'est un fait a journaliser, pas un droit. Le
# controle d'acces appartient aux dependances de BACK-10c.
current_account_id: Final[ContextVar[UUID | None]] = ContextVar("current_account_id", default=None)

# Clinique active du traitement, ou `None` hors de tout perimetre de clinique.
#
# Elle vient de l'en-tete `X-Clinic-Id` (ADR-0012), que la dependance
# `get_active_clinic` (BACK-10c) valide avant de la poser. `None` est l'etat
# normal des routes qui ne travaillent pas sur une clinique precise.
current_clinic_id: Final[ContextVar[UUID | None]] = ContextVar("current_clinic_id", default=None)


@contextmanager
def use_request_id(request_id: str | None) -> Iterator[None]:
    """Pose l'identifiant de requete pour la duree du bloc, puis remet le precedent.

    `reset(token)` et non `set(None)` en sortie : c'est ce qui rend l'imbrication
    correcte -- meme geste que `use_group` dans `tenancy.py`.

    Args:
        request_id: l'identifiant a poser, ou `None` pour executer le bloc hors
            de tout contexte de correlation.

    Yields:
        Rien : le bloc s'execute, le contexte est restaure a sa sortie.
    """
    token = current_request_id.set(request_id)
    try:
        yield
    finally:
        current_request_id.reset(token)


@contextmanager
def use_account_id(account_id: UUID | None) -> Iterator[None]:
    """Pose le compte courant pour la duree du bloc, puis remet le precedent.

    A n'appeler que depuis la bordure : la dependance d'authentification
    (BACK-10c) en production, un test qui compose son contexte. Un cas d'usage
    qui poserait lui-meme cette valeur ferait mentir les journaux.

    Args:
        account_id: le compte a poser, ou `None` pour executer le bloc hors de
            tout contexte de compte.

    Yields:
        Rien : le bloc s'execute, le contexte est restaure a sa sortie.
    """
    token = current_account_id.set(account_id)
    try:
        yield
    finally:
        current_account_id.reset(token)


@contextmanager
def use_clinic_id(clinic_id: UUID | None) -> Iterator[None]:
    """Pose la clinique active pour la duree du bloc, puis remet la precedente.

    Meme regle que `use_account_id` : la valeur vient de la bordure, qui l'a
    validee (l'en-tete `X-Clinic-Id` d'un client n'est pas une autorisation).

    Args:
        clinic_id: la clinique a poser, ou `None` pour executer le bloc hors de
            tout perimetre de clinique.

    Yields:
        Rien : le bloc s'execute, le contexte est restaure a sa sortie.
    """
    token = current_clinic_id.set(clinic_id)
    try:
        yield
    finally:
        current_clinic_id.reset(token)
