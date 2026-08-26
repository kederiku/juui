"""Port du transport de courriel sortant (BACK-22).

CE PORT DIT « FAIRE PARVENIR UN TEXTE A UNE ADRESSE », ET RIEN D'AUTRE
Il ne compose pas de message, ne choisit pas de destinataire, ne consulte
aucune preference : on lui donne une adresse, un objet et un corps en texte
brut, il les remet. Tout ce qui decide -- quel evenement, quel canal, quel
gabarit -- vit au-dessus de lui, dans le module `notifications`.

POURQUOI IL EST DANS `shared/` ET NON DANS `notifications`
La carte de BACK-22 revendique le code SMTP, et le module `notifications` est
bien son premier consommateur. Mais `identity` en a un second usage qui ne peut
PAS passer par lui : le code de verification d'adresse (BACK-17) est un secret
engendre dans le worker, il ne transite ni par la file ni par un autre module
(ADR-0020). Or le contrat `module-independence` interdit a `identity` d'importer
`notifications` : laisser le dialogue SMTP dans le module obligerait a en ecrire
une seconde copie ici ou a percer le contrat. Le transport descend donc au rang
de besoin TECHNIQUE partage, a cote de `Cache` et de `FileStorage`, ou les deux
modules l'atteignent sans se connaitre. L'argumentaire complet est l'ADR-0022.

CE QU'IL FAIT DEVANT UNE PANNE : IL LEVE
Meme reponse que `FileStorage`, et pour la meme raison -- un envoi qui echoue en
silence est un message perdu, dont personne n'apprendra jamais l'absence.
L'appelant, lui, sait quoi en faire : une tache de fond le reprend (BACK-15),
un adaptateur de module le retraduit dans son propre vocabulaire.

TEXTE BRUT, ET C'EST UN CHOIX DU PORT
Aucun parametre HTML. Les messages du service portent un code, une date ou un
lien : le HTML n'y ajouterait qu'une surface -- images distantes, styles, clients
qui les bloquent -- pour une lisibilite qui n'en a pas besoin. Le jour ou un
gabarit riche s'imposera, c'est ce port qui gagnera un parametre, et toutes ses
implementations avec lui.
"""

from abc import ABC, abstractmethod


class EmailDeliveryError(RuntimeError):
    """La remise du courriel a echoue : rien n'est parti.

    UN `RuntimeError` ET NON UNE `DomainError`, comme `OtpDeliveryError` et pour
    le meme motif : rien n'est refuse, c'est le transport qui n'a pas repondu. Le
    destinataire est bon, l'adresse est bonne, le message est bon. Sortir cela en
    4xx mentirait sur la nature de la panne ; elle tombe donc sur le chemin 500
    generique de BACK-09.
    """


class EmailTransport(ABC):
    """Remise d'un courriel a une adresse. Un TRANSPORT, et rien d'autre.

    L'adaptateur qui le remplit vit dans `shared/infrastructure/clients/` ; une
    doublure de test retient les messages au lieu de les expedier, ce qui rend
    tout ce qui envoie du courriel testable sans serveur.
    """

    @abstractmethod
    async def send(self, *, recipient: str, recipient_name: str, subject: str, body: str) -> None:
        """Fait parvenir un message en texte brut a une adresse.

        Args:
            recipient: l'adresse e-mail, deja normalisee par son domaine.
            recipient_name: le nom affiche, pour l'en-tete `To`. La chaine vide
                est admise : l'adresse part alors seule.
            subject: l'objet du message.
            body: le corps, en texte brut.

        Raises:
            EmailDeliveryError: si la remise echoue.
        """
