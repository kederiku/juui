"""Regles metier pures du module scheduling (BACK-21).

Meme doctrine que chez organization et medical_records : une politique est une
regle qui ne tient DANS AUCUNE ENTITE en particulier -- elle s'exprime sur des
valeurs, se teste sans rien construire, et se reutilise d'un cas d'usage a
l'autre. Ce qui n'est vrai que d'une plage donnee reste dans `entities.py`, ou
c'est l'objet-valeur lui-meme qui le fait respecter.

Ce module n'importe RIEN du reste du module scheduling, `entities.py` compris,
hormis `exceptions.py` qui est lui aussi une feuille. C'est ce qui permet aux
entites d'appeler ces regles sans creer de cycle d'import.

POURQUOI UNE HEURE EST ICI UNE MINUTE
Les bornes d'une plage sont des MINUTES DEPUIS MINUIT, entieres, de 0 a 1440
inclus. `datetime.time` ne sait pas dire « jusqu'a minuit » : son maximum est
23:59:59.999999, et surtout `time.fromisoformat("24:00")` rend `time(0, 0)`
SANS lever -- une vacation « 18:00 -> minuit » corrigee a la main produirait
une plage silencieusement inerte, que rien ne signalerait. 1440 exprime la fin
de journee sans sentinelle cachee, et se laisse controler par une simple
`CheckConstraint`.

ET POURQUOI ELLE N'A PAS DE FUSEAU
Ces minutes sont de l'HORLOGE MURALE, celle que le praticien lit au mur de sa
clinique. Le module n'en connait pas le fuseau et n'en invente aucun : le
fuseau est un attribut du LIEU, il appartient a organization, et convertir
« 09:00 » en UTC a l'ecriture figerait le decalage du jour de la saisie -- la
fiche saisie en janvier ouvrirait a 10:00 locales en juillet, et aucune
migration ne saurait plus distinguer l'heure voulue de l'heure figee.
"""

from typing import Final

from app.modules.scheduling.domain.exceptions import InvalidTimeRangeError

# Nombre de minutes dans une journee, et BORNE HAUTE INCLUSE d'une fin de plage.
# 1440 se lit « minuit, fin de journee » ; il n'est jamais un DEBUT valide,
# puisqu'une fin doit lui etre strictement superieure.
MINUTES_PER_DAY: Final = 1440


def format_minute_of_day(value: int) -> str:
    """Rend une minute depuis minuit sous sa forme lisible, `HH:MM`.

    Sert les messages de refus, et rien d'autre : un utilisateur a saisi
    « 18:00 », lui parler de « 1080 » ne l'aiderait pas. 1440 se formate en
    « 24:00 » -- forme que `datetime.time` ne sait justement pas produire.

    Args:
        value: la minute depuis minuit, de 0 a 1440.

    Returns:
        L'heure sur deux fois deux chiffres, separees par deux-points.
    """
    return f"{value // 60:02d}:{value % 60:02d}"


def ensure_valid_minute_range(start_minute: int, end_minute: int) -> None:
    """Refuse une plage horaire mal formee, avant qu'elle n'existe.

    Trois exigences, doublees en base par les contraintes
    `ck_practitioner_hours_range_bounds` et
    `ck_practitioner_hours_minute_of_day_range` : un debut dans la journee, une
    fin qui ne la depasse pas, et une fin STRICTEMENT posterieure au debut.

    La stricte inegalite ecarte du meme geste la plage vide -- « de 09:00 a
    09:00 » ne veut rien dire pour une disponibilite -- et la plage inversee,
    qui serait la porte d'entree du franchissement de minuit. Une garde de nuit
    se saisit en DEUX plages, `22:00 -> 24:00` puis `00:00 -> 02:00` : accepter
    l'enroulement obligerait tout lecteur, pour toujours, a le gerer.

    Args:
        start_minute: le debut de la plage, inclus.
        end_minute: la fin de la plage, exclue.

    Raises:
        InvalidTimeRangeError: si une borne sort de la journee, ou si la fin ne
            suit pas strictement le debut.
    """
    if start_minute < 0 or end_minute > MINUTES_PER_DAY:
        message = (
            f"Une plage horaire tient dans la journee, de 00:00 a 24:00 : "
            f"{start_minute} et {end_minute} n'y tiennent pas."
        )
        raise InvalidTimeRangeError(message)
    if end_minute <= start_minute:
        message = (
            f"La fin d'une plage horaire suit strictement son debut : "
            f"{format_minute_of_day(end_minute)} ne suit pas "
            f"{format_minute_of_day(start_minute)}."
        )
        raise InvalidTimeRangeError(message)


def contains_minute_range(
    start_minute: int, end_minute: int, inner_start: int, inner_end: int
) -> bool:
    """Dit si la premiere plage CONTIENT entierement la seconde.

    C'est la semantique de « disponible » dans ce module, et elle n'est pas le
    chevauchement : un rendez-vous de 09:00 a 10:00 n'est pas servi par une
    disponibilite de 09:30 a 12:00. Le chevauchement se derive de la
    contenance ; l'inverse est faux.

    Args:
        start_minute: le debut de la plage contenante, inclus.
        end_minute: la fin de la plage contenante, exclue.
        inner_start: le debut de la plage cherchee, inclus.
        inner_end: la fin de la plage cherchee, exclue.

    Returns:
        Vrai si la plage cherchee tient tout entiere dans la contenante.
    """
    return start_minute <= inner_start and inner_end <= end_minute


def minute_ranges_overlap(
    first_start: int, first_end: int, second_start: int, second_end: int
) -> bool:
    """Dit si deux plages de la meme journee se recouvrent.

    Les intervalles sont DEMI-OUVERTS, `[start, end)`, comme les fenetres
    datees du depot : deux plages jointives -- l'une finissant quand l'autre
    commence -- ne se chevauchent donc PAS, et la garde de l'agregat les accepte.
    Elle les replie ensuite en une seule (`_validated_hours`), « 09:00-12:00 »
    suivi de « 12:00-18:00 » ne disant rien d'autre que « 09:00-18:00 ».
    Une VRAIE pause de midi, elle, est un TROU : « 09:00-12:00 » et
    « 14:00-18:00 » ne se touchent pas et restent deux plages.

    Args:
        first_start: le debut de la premiere plage, inclus.
        first_end: la fin de la premiere plage, exclue.
        second_start: le debut de la seconde plage, inclus.
        second_end: la fin de la seconde plage, exclue.

    Returns:
        Vrai si les deux plages partagent au moins une minute.
    """
    return first_start < second_end and second_start < first_end
