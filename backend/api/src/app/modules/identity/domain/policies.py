"""Regles metier pures du module identity (BACK-04).

Une politique est une regle qui ne tient DANS AUCUNE ENTITE en particulier :
elle s'exprime sur des valeurs, se teste sans rien construire, et se reutilise
d'un cas d'usage a l'autre. Ce qui n'est vrai que d'un compte donne -- ses
transitions de statut, par exemple -- reste dans `entities.py`, ou c'est
l'entite elle-meme qui le fait respecter.

Ce module n'importe RIEN du reste du module identity, `entities.py` compris.
C'est ce qui permet a l'entite d'appeler ces regles dans sa fabrique sans
creer de cycle d'import, et ce n'est pas un hasard : une politique qui aurait
besoin de connaitre l'entite serait un comportement de l'entite.

CE QUE LES TICKETS SUIVANTS AJOUTERONT ICI
La politique de mot de passe et la verification HIBP arrivent en BACK-10b sous
la forme d'un objet-valeur `Password` ; les regles de canal d'inscription
(« seuls les comptes particuliers s'inscrivent seuls ») viennent avec BACK-28.
"""


def normalize_email(value: str) -> str:
    """Ramene une adresse e-mail a sa forme canonique.

    Une seule forme est ECRITE en base : minuscules, sans espaces de garde. Sans
    cette regle, « Jean@Exemple.fr » et « jean@exemple.fr » creeraient deux
    comptes pour une seule personne, et la seconde inscription passerait le
    controle d'unicite sans broncher.

    La regle est ici parce qu'elle est METIER : la base la fait respecter de
    son cote avec l'index `ix_accounts_email_lower` (INFRA-09, ADR-0016), mais
    un index refuse, il ne normalise pas -- l'utilisateur recevrait un conflit
    la ou il attend un compte.

    Args:
        value: l'adresse telle que saisie.

    Returns:
        L'adresse en minuscules, debarrassee de ses espaces de garde.
    """
    return value.strip().lower()


def normalize_phone(value: str | None) -> str | None:
    """Ramene un numero de telephone a une forme comparable.

    Volontairement MINIMALE : on retire les espaces, points et tirets de mise en
    forme, on ne reformate pas et on ne valide pas. Un numero se saisit de dix
    facons (« 06 12 34 56 78 », « 06.12.34.56.78 », « +33612345678 ») et aucune
    n'est fausse ; la normalisation E.164, elle, suppose un pays connu, ce que
    l'inscription ne demande pas.

    Args:
        value: le numero tel que saisi, ou None -- le telephone est facultatif.

    Returns:
        Le numero sans separateurs de mise en forme, None si rien n'a ete saisi,
        None egalement si la saisie ne contenait que des separateurs.
    """
    if value is None:
        return None
    compacted = value.translate(str.maketrans("", "", " .-"))
    return compacted or None
