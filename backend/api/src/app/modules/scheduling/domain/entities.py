"""Agregats du module scheduling (BACK-21).

`identity` repond a « peux-tu prouver qui tu es », `organization` a « dans
quelle structure travailles-tu », `medical_records` a « de quels animaux
s'agit-il » ; celui-ci repond a « quand, avec qui, pour quel acte ». Un seul
agregat pour l'instant, et une decision qui est LA decision du ticket
(ADR-0026) :

- `PractitionerProfile` : la « fiche technique » du cahier des charges -- les
  horaires d'intervention d'un praticien et les especes qu'il prend en charge.

POURQUOI ICI ET PAS DANS IDENTITY
Des horaires d'intervention sont une DISPONIBILITE ; des especes prises en
charge sont une COMPETENCE, celle qui appariera un praticien et un animal. Les
deux sont consommees par la prise de rendez-vous, jamais par l'authentification.
Que le formulaire vive dans l'ecran « mon compte » est une commodite d'IHM, pas
une decision de modele : les laisser dans identity ferait de la table des
comptes le fourre-tout que le decoupage en modules cherche a eviter, et
obligerait scheduling a lire chez identity.

PORTEE PAR LA CLINIQUE, PAS PAR LE COMPTE
La fiche est identifiee par le couple `(account_id, clinic_id)` a l'interieur
d'un groupe. Un veterinaire remplacant n'a pas les memes horaires selon la
structure ou il intervient, ni forcement les memes especes : une fiche par
compte serait l'erreur meme que ce ticket sort d'identity, et elle serait
irreversible. Le ticket dit « portee par l'AFFECTATION » ; ce sont les
COORDONNEES de l'affectation qui portent la fiche, pas son identite -- une
affectation est datee et se renouvelle, une fiche pendue a son identifiant
deviendrait orpheline a chaque contrat. Et `assignments` appartient a
organization : ADR-0015 interdit la cle etrangere qui traverserait la frontiere.

PAS DE `group_id`, ET C'EST DELIBERE
L'agregat est TENANT : sa colonne de groupe est estampillee par le socle a
l'insertion (BACK-06b), jamais par le mapping du module -- meme regle que
`Clinic` et `Assignment` chez organization.

PAS DE FENETRE DE VALIDITE NON PLUS
Ni `start_at` ni `end_at` : la portee du ticket exclut les conges et les
exceptions. Corollaire ASSUME et nomme jusque dans le port : une fiche survit a
l'affectation qui l'a motivee, et c'est a l'appelant de croiser la
disponibilite DECLAREE avec les affectations ACTIVES d'organization.

LES HEURES SONT DES MINUTES D'HORLOGE MURALE
Jamais des instants. Le module ne connait aucun fuseau et n'en invente aucun --
voir la docstring de `policies.py`, qui porte les deux raisons.
"""

from calendar import Day
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from itertools import pairwise
from typing import Self
from uuid import UUID, uuid7

from app.modules.scheduling.domain.exceptions import OverlappingTimeRangesError
from app.modules.scheduling.domain.policies import (
    contains_minute_range,
    ensure_valid_minute_range,
    format_minute_of_day,
    minute_ranges_overlap,
)


class Species(StrEnum):
    """Espece prise en charge par un praticien : ensemble FERME, comme ailleurs.

    HOMONYME ASSUME DE `medical_records.Species`, ET VOLONTAIREMENT IDENTIQUE
    Le contrat `module-independence` interdit a scheduling d'importer l'enum de
    medical_records -- directement comme par chaine --, et le precedent
    enterine du depot est de RECOPIER plutot que de faire descendre le
    vocabulaire dans `shared/` : BACK-10a a recopie les trois types de compte
    d'identity, et une garde de non-derive les tient. La notre est
    `tests/modules/scheduling/test_species_vocabulary.py`, qui a le droit
    d'importer les deux cotes parce que `tests/` est hors du graphe
    d'import-linter. Le supprimer doit etre un acte visible en diff, dans la
    meme pull request, avec l'ecart consigne au registre.

    LES DEUX ENUMS NE DISENT D'AILLEURS PAS LA MEME CHOSE
    Chez medical_records, l'espece est une IDENTITE : cet animal EST un chien.
    Ici c'est une COMPETENCE : ce praticien PREND EN CHARGE les chiens. `OTHER`
    y accueille l'espece imprevue vue a l'accueil ; ici il declare « je prends
    les especes hors catalogue », ce qui est le fait des praticiens NAC.

    Stocke en texte (`String(20)`, jamais d'enum natif PostgreSQL) : ajouter une
    espece est une livraison de code, pas une migration.
    """

    DOG = "dog"
    CAT = "cat"
    FERRET = "ferret"
    RABBIT = "rabbit"
    RODENT = "rodent"
    BIRD = "bird"
    REPTILE = "reptile"
    HORSE = "horse"
    OTHER = "other"


@dataclass(frozen=True, slots=True, kw_only=True, order=True)
class WeeklyTimeRange:
    """Une plage d'intervention hebdomadaire : un jour, deux minutes.

    GELEE, comme tout objet-valeur : ce qui a ete declare ne se corrige pas en
    chemin, on remplace la plage entiere. `order=True` la rend triable par
    `(weekday, start_minute, end_minute)`, ce qui donne a la fiche son ordre
    canonique sans comparateur ecrit a la main.

    CONTRAIREMENT AUX AGREGATS, LE CONSTRUCTEUR NU N'EST PAS UNE EXEMPTION
    Un agregat se reconstitue depuis la persistance sans repasser par sa
    fabrique ; un objet-valeur, lui, EST ses valeurs -- une combinaison
    invalide n'est pas la meme plage mal formee, c'est rien du tout. Le depot
    passe donc lui aussi par `create()` a la relecture : une ligne corrompue
    LEVE au lieu de produire une plage silencieusement inerte.

    Attributes:
        weekday: le jour de la semaine, dans la convention de la bibliotheque
            standard -- `calendar.Day`, lundi = 0, celle que rend
            `date.weekday()`.
        start_minute: le debut, en minutes depuis minuit, inclus.
        end_minute: la fin, en minutes depuis minuit, exclue. 1440 vaut
            « minuit, fin de journee ».
    """

    weekday: Day
    start_minute: int
    end_minute: int

    @classmethod
    def create(cls, *, weekday: Day, start_minute: int, end_minute: int) -> Self:
        """Cree une plage horaire, bornes validees.

        Args:
            weekday: le jour de la semaine.
            start_minute: le debut, en minutes depuis minuit, inclus.
            end_minute: la fin, en minutes depuis minuit, exclue.

        Returns:
            La plage, prete a rejoindre une fiche.

        Raises:
            InvalidTimeRangeError: si une borne sort de la journee, ou si la
                fin ne suit pas strictement le debut.
        """
        ensure_valid_minute_range(start_minute, end_minute)
        return cls(weekday=weekday, start_minute=start_minute, end_minute=end_minute)

    def covers(self, other: WeeklyTimeRange) -> bool:
        """Dit si cette plage contient entierement l'autre, le meme jour.

        C'est la question que pose l'appariement : « ce praticien est-il
        disponible sur CE creneau ». La contenance, pas le chevauchement -- une
        disponibilite de 09:30 a 12:00 ne sert pas un rendez-vous de 09:00 a
        10:00.

        Args:
            other: la plage cherchee.

        Returns:
            Vrai si les deux plages tombent le meme jour et que l'autre tient
            tout entiere dans celle-ci.
        """
        return self.weekday == other.weekday and contains_minute_range(
            self.start_minute, self.end_minute, other.start_minute, other.end_minute
        )

    def overlaps(self, other: WeeklyTimeRange) -> bool:
        """Dit si les deux plages partagent au moins une minute.

        Le jour fait partie de l'identite d'une plage : deux plages de jours
        differents ne se chevauchent jamais, quelles que soient leurs heures.

        Args:
            other: la plage comparee.

        Returns:
            Vrai si les deux plages tombent le meme jour et se recouvrent.
        """
        return self.weekday == other.weekday and minute_ranges_overlap(
            self.start_minute, self.end_minute, other.start_minute, other.end_minute
        )

    def __str__(self) -> str:
        """Rend la plage lisible, pour les messages de refus.

        Returns:
            Le jour et les deux bornes, par exemple `MONDAY 09:00-12:00`.
        """
        start = format_minute_of_day(self.start_minute)
        end = format_minute_of_day(self.end_minute)
        return f"{self.weekday.name} {start}-{end}"


def ensure_hours_disjoint(hours: Sequence[WeeklyTimeRange]) -> None:
    """Refuse deux plages du meme jour qui se recouvrent.

    Fonction de SERVICE et non methode, meme statut qu'`ensure_assignment_allowed`
    chez organization : la regle porte sur la COLLECTION, et aucune plage prise
    seule ne la contient. Elle n'a en revanche besoin d'AUCUNE lecture prealable
    -- l'invariant porte sur le contenu de l'agregat, ecrit et relu d'un bloc.

    RECOUVREMENT ET ADJACENCE NE SONT PAS LA MEME CHOSE
    Un RECOUVREMENT est une contradiction : « 09:00-12:00 » et « 11:00-14:00 »
    disent deux fois autre chose de la meme minute, et le domaine refuse plutot
    que de reecrire la saisie -- il ne repare jamais en douce. Deux plages
    JOINTIVES, elles, ne se contredisent pas : « 09:00-12:00 » et « 12:00-18:00 »
    designent exactement les memes minutes que « 09:00-18:00 », et rien dans une
    plage ne distingue deux troncons contigus. Elles passent donc cette garde, et
    `_validated_hours` les replie ensuite en une seule -- voir sa docstring, qui
    dit pourquoi la forme canonique n'est pas cosmetique.

    La base tient sa moitie de la regle -- la cle naturelle
    `(profile_id, weekday, start_minute)` interdit deja deux plages commencant a
    la meme heure le meme jour -- mais pas le recouvrement partiel : PostgreSQL
    n'a pas de type intervalle natif sur des minutes, et une contrainte
    `EXCLUDE` demanderait `btree_gist` et un type de plage.

    Args:
        hours: les plages de la fiche, dans un ordre quelconque.

    Raises:
        OverlappingTimeRangesError: des la premiere paire qui se recouvre, en
            nommant les deux plages fautives.
    """
    for previous, current in pairwise(sorted(hours)):
        if previous.overlaps(current):
            message = (
                f"Deux plages d'intervention se recouvrent le meme jour : {previous} et {current}."
            )
            raise OverlappingTimeRangesError(message)


@dataclass(slots=True, kw_only=True)
class PractitionerProfile:
    """Fiche technique d'un praticien dans UNE clinique : horaires et competences.

    Construire l'objet directement est reserve a la RECONSTITUTION depuis la
    persistance ; une creation metier passe par `PractitionerProfile.create()`.

    `account_id` et `clinic_id` restent des identifiants NUS : le compte vit
    chez identity, la clinique chez organization, et aucun des trois modules ne
    s'importe (ADR-0015). PAS de champ de groupe : l'agregat est tenant, et
    l'estampillage est l'affaire du socle.

    LES PLAGES SONT TENUES SOUS FORME CANONIQUE
    Triees, sans recouvrement, et MAXIMALES : deux plages jointives saisies
    separement sont repliees en une seule. C'est ce qui rend exact le predicat
    mono-plage d'`is_available_for` et de son jumeau SQL. La regle vaut a
    l'ECRITURE -- la reconstitution depuis la persistance ne la rejoue pas, et
    les deux couches restent d'accord sur une ligne non canonique, toutes deux
    par plage.

    UNE FICHE VIDE EST UN ETAT NOMINAL
    Aucune plage, aucune espece : c'est l'etat a l'ouverture de l'ecran « mon
    compte », et il rend le praticien invisible de l'appariement. L'ensemble
    vide vaut « rien de declare », JAMAIS « toutes les especes » -- la
    distinction est la meme que celle des preferences de notifications, et la
    confondre proposerait un praticien pour un animal qu'il ne soigne pas.
    """

    id: UUID
    account_id: UUID
    clinic_id: UUID
    hours: tuple[WeeklyTimeRange, ...] = ()
    treated_species: frozenset[Species] = field(default_factory=frozenset)

    @classmethod
    def create(
        cls,
        *,
        account_id: UUID,
        clinic_id: UUID,
        hours: Iterable[WeeklyTimeRange] = (),
        treated_species: Iterable[Species] = (),
    ) -> Self:
        """Cree une fiche neuve, identifiee par le domaine et invariant verifie.

        Args:
            account_id: le compte du praticien -- identifiant nu, jamais
                l'entite d'identity.
            clinic_id: la clinique ou il intervient -- identifiant nu, jamais
                l'entite d'organization.
            hours: ses plages d'intervention, dans un ordre quelconque ; elles
                ressortent triees, et deux plages jointives du meme jour
                ressortent repliees en une seule.
            treated_species: les especes qu'il prend en charge ; les doublons
                s'effondrent, l'ensemble n'ayant pas a s'en soucier.

        Returns:
            Une fiche prete a etre persistee, dans le groupe du contexte.

        Raises:
            OverlappingTimeRangesError: si deux plages du meme jour se
                recouvrent.
        """
        return cls(
            id=uuid7(),
            account_id=account_id,
            clinic_id=clinic_id,
            hours=_validated_hours(hours),
            treated_species=frozenset(treated_species),
        )

    def set_hours(self, hours: Iterable[WeeklyTimeRange]) -> None:
        """Remplace les plages d'intervention, invariant revalide.

        SEULE methode de mutation de l'agregat, et elle existe parce qu'une
        REGLE existe : sans la disjonction a faire respecter, remplacer un
        champ ne meriterait pas de methode. Il n'y a deliberement pas de
        `set_treated_species` -- un `frozenset` n'a aucune regle a tenir, et une
        methode qui se contenterait d'affecter donnerait a croire le contraire.

        Args:
            hours: les nouvelles plages, dans un ordre quelconque ; elles
                ressortent sous la forme canonique -- triees, et jointives
                repliees.

        Raises:
            OverlappingTimeRangesError: si deux plages du meme jour se
                recouvrent -- l'invariant n'est pas vrai qu'a la naissance.
        """
        self.hours = _validated_hours(hours)

    def is_available_for(self, *, time_range: WeeklyTimeRange, species: Species) -> bool:
        """Dit si le praticien a declare pouvoir prendre ce creneau et cette espece.

        LE JUMEAU DOMAINE DU PREDICAT SQL de `list_available` : les deux
        repondent a la meme question, l'un en memoire et sans Docker, l'autre en
        base. Toute modification de l'un se fait dans le MEME commit que
        l'autre, et `test_sql_and_domain_answer_with_one_voice` les confronte.

        DECLARE, et rien de plus : ni conges, ni exceptions, ni rendez-vous deja
        pris, ni affectation encore en cours -- voir la docstring du port.

        Args:
            time_range: le creneau cherche.
            species: l'espece a prendre en charge.

        Returns:
            Vrai si l'espece figure aux competences ET qu'une plage declaree
            contient entierement le creneau.
        """
        return species in self.treated_species and any(
            declared.covers(time_range) for declared in self.hours
        )


def _validated_hours(hours: Iterable[WeeklyTimeRange]) -> tuple[WeeklyTimeRange, ...]:
    """Met les plages sous forme canonique : triees, disjointes et MAXIMALES.

    L'ordre canonique est celui de `WeeklyTimeRange` -- `(weekday,
    start_minute, end_minute)`. Le tenir dans l'entite plutot qu'a l'affichage
    rend deux fiches au meme etat comparables champ a champ, et evite que deux
    enregistrements du meme contenu produisent deux jeux de lignes distincts.

    LES PLAGES JOINTIVES SONT REPLIEES, ET CE N'EST PAS UNE COQUETTERIE
    `is_available_for` -- et son jumeau SQL -- demandent qu'UNE plage declaree
    contienne le creneau cherche. Saisies telles quelles, « 09:00-12:00 » et
    « 12:00-18:00 » ne repondraient donc PAS a une demande de 11:30 a 12:30 : le
    praticien, pourtant present sans interruption de 09:00 a 18:00, disparaitrait
    de la requete du ticket, en silence. Les replier en « 09:00-18:00 » rend le
    predicat mono-plage exact, sans rien perdre -- une plage ne porte aucun
    attribut qui distinguerait deux troncons contigus -- et sans compliquer le
    SQL, qui reste un `EXISTS` sur une seule ligne fille.

    Une vraie pause de midi, elle, est un TROU : « 09:00-12:00 » et
    « 14:00-18:00 » ne sont pas jointives et restent deux plages. La forme
    canonique ne fusionne que ce qui se touche.

    Args:
        hours: les plages, dans un ordre quelconque.

    Returns:
        Les plages triees, repliees et sans recouvrement, en tuple --
        l'agregat ne prete pas une liste que l'appelant pourrait modifier dans
        son dos.

    Raises:
        OverlappingTimeRangesError: si deux plages du meme jour se recouvrent.
    """
    ordered = tuple(sorted(hours))
    ensure_hours_disjoint(ordered)
    return _merged_hours(ordered)


def _merged_hours(ordered: Sequence[WeeklyTimeRange]) -> tuple[WeeklyTimeRange, ...]:
    """Replie en une seule plage toute suite de plages jointives du meme jour.

    Un balayage lineaire suffit : les plages arrivent triees et sans
    recouvrement, si bien que deux plages a replier sont toujours voisines.

    Args:
        ordered: les plages, deja triees et deja verifiees disjointes.

    Returns:
        Les plages maximales, dans le meme ordre.
    """
    merged: list[WeeklyTimeRange] = []
    for current in ordered:
        previous = merged[-1] if merged else None
        if (
            previous is not None
            and previous.weekday == current.weekday
            and previous.end_minute == current.start_minute
        ):
            merged[-1] = WeeklyTimeRange.create(
                weekday=previous.weekday,
                start_minute=previous.start_minute,
                end_minute=current.end_minute,
            )
        else:
            merged.append(current)
    return tuple(merged)
