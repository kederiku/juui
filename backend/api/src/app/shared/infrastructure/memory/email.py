"""Doublure en memoire du port `EmailTransport` (BACK-06c).

Elle retient les messages au lieu de les expedier, ce qui rend testable sans
serveur SMTP tout ce qui envoie du courriel -- l'adaptateur de canal e-mail de
`notifications` comme l'expediteur de code de verification d'`identity`, les deux
consommateurs que l'ADR-0022 a fait converger sur ce port.

ELLE VIT DANS `shared/` PARCE QUE SON PORT Y VIT. La doublure suit toujours son
port : celui du transport est technique et partage, celui de `NotificationSender`
est metier et reste dans son module. C'est la meme regle qui range les deux, pas
deux arbitrages distincts.

L'ECHEC EST SIMULABLE, ET IL LEVE : ce port ne degrade pas -- un message perdu en
silence est un message dont personne n'apprendra jamais l'absence.
"""

from dataclasses import dataclass, field

from app.shared.domain.ports.email import EmailDeliveryError, EmailTransport


@dataclass(slots=True)
class SentEmail:
    """Un courriel observe par la doublure de transport.

    Attributes:
        recipient: l'adresse visee.
        recipient_name: le nom affiche.
        subject: l'objet du message.
        body: le corps, en texte brut.
    """

    recipient: str
    recipient_name: str
    subject: str
    body: str


@dataclass(slots=True)
class FakeEmailTransport(EmailTransport):
    """Transport qui retient les messages au lieu de les expedier.

    Attributes:
        fails: si vrai, chaque remise leve `EmailDeliveryError` sans rien retenir.
            RIEN N'EST RETENU sur echec, a dessein : le port promet qu'un envoi
            en echec n'est pas parti, et une doublure qui garderait la trace d'un
            message non remis ferait passer un test de reprise qui compte les
            envois.
        sent: les messages remis, dans l'ordre.
    """

    fails: bool = False
    sent: list[SentEmail] = field(default_factory=list)

    async def send(self, *, recipient: str, recipient_name: str, subject: str, body: str) -> None:
        """Retient le message au lieu de l'expedier -- ou echoue, sur demande.

        Args:
            recipient: l'adresse e-mail, deja normalisee.
            recipient_name: le nom affiche. La chaine vide est admise.
            subject: l'objet du message.
            body: le corps, en texte brut.

        Raises:
            EmailDeliveryError: si l'echec est simule.
        """
        if self.fails:
            raise EmailDeliveryError("Panne simulee du transport de courriel.")
        self.sent.append(
            SentEmail(
                recipient=recipient,
                recipient_name=recipient_name,
                subject=subject,
                body=body,
            )
        )

    @property
    def last(self) -> SentEmail:
        """Le dernier message remis.

        `raise AssertionError` ET NON UNE INSTRUCTION `assert`, ici et dans
        toutes les doublures : la regle Ruff `S` refuse `assert` hors de
        `tests/`, et elle a raison -- `python -O` l'efface, et cette garde
        deviendrait un `IndexError` nu. L'exception, elle, est la bonne : c'est
        le TEST qui se trompe de cible en lisant un envoi qui n'a pas eu lieu.

        Returns:
            Le dernier courriel retenu.

        Raises:
            AssertionError: si rien n'est parti.
        """
        if not self.sent:
            message = "Aucun courriel n'est parti."
            raise AssertionError(message)
        return self.sent[-1]
