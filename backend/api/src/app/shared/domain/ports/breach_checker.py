"""Port du controle de fuite de mot de passe (port pose par BACK-06c, adaptateur en BACK-10b).

Le contrat, jamais son adaptateur : ce module ne connait ni Have I Been Pwned, ni
le SHA-1, ni la k-anonymity, ni le reseau. Il dit ce que le domaine a besoin de
savoir -- « ce mot de passe est-il connu des fuites publiques ? » -- et laisse a
`shared/infrastructure/clients/` le soin d'aller le demander a quelqu'un.

POURQUOI CE PORT NAIT ICI, AVANT SON ADAPTATEUR
BACK-10b porte la politique de mot de passe et l'adaptateur HIBP ; ce ticket-ci
ne livre que ce sans quoi `FakeBreachChecker` ne pourrait pas exister -- une
doublure repond a un port, elle n'en invente pas un. Ce qui reste entier a
BACK-10b : l'appel en k-anonymity (seuls les cinq premiers caracteres du SHA-1
partent), le hachage argon2id, l'objet-valeur `Password` et ses bornes.

CE QU'IL FAIT DEVANT UNE PANNE : IL DEGRADE
Troisieme comportement du quatuor, et le plus contre-intuitif. `FileStorage` et
`EmailTransport` LEVENT, `AbstractUnitOfWork` LEVE ET ANNULE, `Cache` DEGRADE
parce qu'un cache absent ne change qu'une latence. Celui-ci degrade pour une
raison differente et qu'il faut avoir en tete avant de l'inverser : refuser une
inscription parce qu'un service TIERS ne repond pas coute plus cher que le risque
couvert. Un mot de passe faible qui passe est un compte a risque ; une inscription
impossible est un service en panne pour tout le monde.

LA DEGRADATION VA DANS LE SENS PERMISSIF, ET SEULEMENT ICI. Un port de securite
echoue normalement FERME -- `OtpStore` leve plutot que de rendre un verdict, et sa
docstring dit pourquoi. La difference tient a ce que la reponse par defaut
autorise : « cet OTP a-t-il ete consomme ? » repondu « non » ouvre la porte a
quelqu'un qui n'a pas le code ; « ce mot de passe a-t-il fuite ? » repondu « non »
laisse passer un mot de passe que l'utilisateur a lui-meme choisi. Ne pas
generaliser l'un a l'autre.
"""

from abc import ABC, abstractmethod


class BreachChecker(ABC):
    """Dit si un mot de passe figure dans les fuites publiques connues.

    DEUX REGLES QUI ENGAGENT TOUTE IMPLEMENTATION

    1. LE MOT DE PASSE NE SORT PAS DU PROCESSUS. Le port recoit le secret en
       clair parce qu'il faut bien le condenser quelque part ; ce que
       l'implementation a le droit d'emettre sur le reseau appartient a
       l'adaptateur, et BACK-10b le borne a un prefixe d'empreinte. Aucune
       implementation ne journalise le mot de passe, ni son empreinte complete.

    2. L'INDISPONIBILITE REND `False`. Voir la docstring de module : un
       verificateur muet accepte, il ne bloque pas. Elle le JOURNALISE en
       revanche -- une degradation silencieuse est une regle de securite qui
       cesse de s'appliquer sans que personne l'apprenne.
    """

    @abstractmethod
    async def is_breached(self, password: str) -> bool:
        """Dit si ce mot de passe est connu des fuites publiques.

        Args:
            password: le mot de passe en clair, tel que l'utilisateur l'a saisi.

        Returns:
            Vrai s'il figure dans les fuites connues. FAUX AUSSI quand le
            service interroge ne repond pas -- relire la regle 2 avant d'en
            faire une condition de securite dure.
        """
