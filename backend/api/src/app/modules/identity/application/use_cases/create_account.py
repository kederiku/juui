"""Cas d'usage pilote : creer un compte (BACK-04).

Il existe pour DEMONTRER le trajet complet -- schema d'API, commande, entite,
modele de persistance -- sur un exemple qui ecrit reellement. C'est le sens que
demande le critere d'acceptation du ticket.

CE QUE CE CAS D'USAGE NE FAIT PAS, ET POURQUOI
Il ne hache aucun mot de passe (BACK-10b), n'envoie aucun code de verification
(BACK-17) et n'applique PAS la regle de non-divulgation du parcours
d'inscription (BACK-09, BACK-28) -- il leve `EmailAlreadyUsedError` en clair,
ce qui convient a une creation administrative mais ferait du formulaire
d'inscription publique un oracle d'existence de compte. BACK-28 reprendra ce
trajet dans `register_individual`, qui portera ces trois regles.

CE QUE BACK-06a CHANGERA ICI
Le depot est injecte directement ; il le sera par l'unite de travail, ce qui
apportera l'atomicite et le `commit`. La regle qui compte est deja tenue : AUCUNE
session de base de donnees n'entre dans un cas d'usage. Ce qui arrive ici est un
port, pas une technologie.
"""

from dataclasses import dataclass

from app.modules.identity.domain.entities import Account, AccountType
from app.modules.identity.domain.exceptions import EmailAlreadyUsedError
from app.modules.identity.domain.policies import normalize_email
from app.modules.identity.domain.ports import AccountRepository


@dataclass(frozen=True, slots=True)
class CreateAccountCommand:
    """Ce dont le cas d'usage a besoin, exprime sans aucun vocabulaire HTTP.

    Ce n'est PAS un quatrieme modele du compte : la commande decrit une
    INTENTION, pas un etat persistant. Elle existe pour que le cas d'usage
    puisse etre appele depuis une route, une tache de fond ou une commande en
    ligne sans que sa signature change a chaque fois.

    Gelee (`frozen`) a dessein : une commande deja transmise ne se corrige pas
    en chemin.
    """

    email: str
    first_name: str
    last_name: str
    account_type: AccountType
    phone: str | None = None


class CreateAccount:
    """Cree un compte dont l'adresse n'est pas encore prise."""

    def __init__(self, accounts: AccountRepository) -> None:
        """Memorise le port par lequel les comptes sont lus et ecrits.

        Args:
            accounts: le depot de comptes. Un PORT, jamais une session : c'est
                l'assemblage (la route, le test, la tache) qui decide quel
                adaptateur arrive ici.
        """
        self._accounts = accounts

    async def execute(self, command: CreateAccountCommand) -> Account:
        """Applique la commande et retourne le compte cree.

        Args:
            command: l'intention de creation.

        Returns:
            Le compte cree, ACTIF et non verifie, identifiant deja attribue.

        Raises:
            EmailAlreadyUsedError: si un compte porte deja cette adresse.
        """
        # Normalisation AVANT la recherche, et non apres : chercher
        # « Jean@Exemple.fr » tel quel ne trouverait pas le « jean@exemple.fr »
        # deja enregistre, et le controle d'unicite laisserait passer le
        # doublon qu'il est cense arreter. `Account.create` normalise a son
        # tour -- l'entite ne delegue pas la garde de son invariant a
        # l'appelant.
        email = normalize_email(command.email)
        if await self._accounts.find_by_email(email) is not None:
            message = "Un compte utilise deja cette adresse e-mail."
            raise EmailAlreadyUsedError(message)

        account = Account.create(
            email=email,
            first_name=command.first_name,
            last_name=command.last_name,
            account_type=command.account_type,
            phone=command.phone,
        )
        await self._accounts.add(account)
        return account
