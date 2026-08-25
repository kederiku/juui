"""Convention de nommage des cles du stockage objet (BACK-13).

C'est ici, et NULLE PART AILLEURS, qu'un nom de fichier fourni par un utilisateur
devient une cle d'objet :

    {entity_type}/{entity_id}/{nom de fichier assaini}

Par exemple `animal-photos/0193.../radio-patte-avant.jpg`. Le segment central est
un UUID, ce qui rend deux televersements du meme nom impossibles a confondre --
la collision que le ticket demande d'eviter.

DEUX FONCTIONS, ET LEUR PARTAGE DU TRAVAIL
`build_storage_key` compose une cle CONFORME a la convention ci-dessus : c'est ce
qu'appelle le code qui enregistre un fichier. `validate_storage_key` verifie
qu'une cle est SANS DANGER : c'est ce qu'appelle l'adaptateur, sur chaque cle
qu'il recoit, sans lui imposer la forme ci-dessus. La distinction n'est pas
theorique -- une cle relue d'une colonne de base a ete composee par une version
anterieure du service, et la refuser sur un changement de convention rendrait
illisibles des fichiers parfaitement valides. Ce qui doit etre refuse sans
discussion, c'est ce qui SORT de son prefixe.

POURQUOI CE MODULE N'A PAS DE CLASSE, CONTRAIREMENT A `cache_keys.py`
`CacheKeyBuilder` porte un etat : l'environnement, fixe pour la duree du
processus. Ici il n'y a rien a porter -- ni environnement (les environnements ont
des BUCKETS distincts, la separation est faite un cran au-dessus), ni groupe
(voir plus bas). Deux fonctions disent donc exactement ce qu'il y a a dire, la ou
une classe sans champ ne serait qu'un ceremonial.

AUCUN SEGMENT DE TENANCE, ET C'EST DELIBERE
Une cle de cache est volatile ; une cle de stockage est PERSISTEE en base. La
faire dependre de `current_group_id` la rendrait introuvable des que le contexte
differe de celui de l'ecriture -- une tache de fond (BACK-15), un export, ou
simplement un veterinaire remplacant qui a change de structure entre-temps. Le
cloisonnement entre groupes appartient a l'AUTORISATION : qui a le droit de
demander une URL pre-signee pour cette cle. Il ne peut pas appartenir au nommage
d'une donnee durable.
"""

import re
import unicodedata
from typing import Final
from uuid import UUID

from app.shared.domain.ports.file_storage import InvalidStorageKeyError

# Separateur de segments : la barre oblique, qui n'a rien de special pour S3 mais
# que toutes les consoles d'inspection presentent en arborescence.
_SEPARATOR: Final = "/"

# Forme admise pour un type d'entite : minuscules, chiffres et tirets.
#
# UN MOTIF ET NON UNE ENUMERATION. Le style du depot voudrait un `StrEnum` avec
# un `assert_never`, comme pour `CacheScope` -- mais les entites qui portent des
# fichiers naissent avec BACK-19 et BACK-20. Enumerer aujourd'hui reviendrait a
# inventer leur domaine, puis a le corriger. Le motif garde ce qui compte des a
# present : pas de majuscule, pas d'espace, pas de barre oblique clandestine.
_ENTITY_TYPE_PATTERN: Final = re.compile(r"\A[a-z][a-z0-9-]{0,63}\Z")

# Tout ce qui n'est ni lettre latine, ni chiffre, ni point, tiret ou tiret bas est
# remplace. La liste est volontairement etroite : ces caracteres-la traversent
# sans dommage une URL, un en-tete `Content-Disposition` et un systeme de fichiers
# Windows, ce qu'aucun jeu plus large ne garantit.
_UNSAFE_FILENAME_CHARS: Final = re.compile(r"[^A-Za-z0-9._-]+")

# Repetitions de separateurs produites par le remplacement ci-dessus.
_REPEATED_SEPARATORS: Final = re.compile(r"-{2,}")

# Longueur maximale du nom de fichier conserve dans la cle. Le nom n'a pas a etre
# integral : il sert a rendre la cle LISIBLE dans une console d'inspection, pas a
# restituer le nom d'origine -- celui-la se range en base, a cote de la cle.
_MAX_FILENAME_LENGTH: Final = 120

# Nom de repli quand l'assainissement ne laisse rien du radical. Un fichier dont
# le nom est entierement non latin ne doit pas produire une cle qui se termine par
# une barre oblique -- elle designerait un prefixe et non un objet.
_FALLBACK_FILENAME: Final = "fichier"

# Longueur maximale de ce qui peut passer pour une extension. Au-dela, ou des que
# le fragment n'est pas purement alphanumerique, le point qui le precede n'est
# qu'un point dans un nom : « rapport.2026.sauvegarde-du-15-janvier » n'a pas
# d'extension, et lui en decouper une produirait un nom tronque a la place d'un
# nom entier.
_MAX_SUFFIX_LENGTH: Final = 12

# Longueur maximale d'une cle S3, en OCTETS UTF-8 et non en caracteres. La borne
# vient d'Amazon et MinIO l'applique aussi. Depassee, la requete echoue cote
# serveur avec un message que personne ne relie a un nom de fichier trop long.
_MAX_KEY_BYTES: Final = 1024


def build_storage_key(entity_type: str, entity_id: UUID, filename: str) -> str:
    """Compose la cle d'un fichier attache a une entite.

    Args:
        entity_type: la famille de l'entite proprietaire, en minuscules et tirets
            -- `animal-photos`, `medical-documents`.
        entity_id: l'identifiant de l'entite. Un `UUID` et non une chaine : le
            type interdit de passer par megarde un identifiant devinable, et il
            garantit la forme du segment sans avoir a la valider.
        filename: le nom d'origine, tel que l'utilisateur l'a fourni. Il est
            assaini, jamais repris tel quel.

    Returns:
        La cle complete, prete a etre persistee.

    Raises:
        InvalidStorageKeyError: si le type d'entite ne respecte pas la convention,
            ou si la cle produite depasse la longueur admise par le stockage.
    """
    if not _ENTITY_TYPE_PATTERN.fullmatch(entity_type):
        message = (
            f"Type d'entite invalide pour une cle de stockage : {entity_type!r}. "
            "Attendu : minuscules, chiffres et tirets, commencant par une lettre."
        )
        raise InvalidStorageKeyError(message)
    key = _SEPARATOR.join((entity_type, str(entity_id), _sanitize_filename(filename)))
    return validate_storage_key(key)


def validate_storage_key(key: str) -> str:
    """Refuse une cle dangereuse, et rend les autres telles quelles.

    CE QUE CETTE FONCTION EMPECHE
    Le seul cloisonnement des fichiers d'une entite est leur PREFIXE de cle. Une
    cle contenant `..` le traverse : `animal-photos/{a}/../../{b}/dossier.pdf`
    designe le fichier d'une AUTRE entite, et les clients S3 -- boto3 compris --
    normalisent les chemins avant de signer. Les octets de controle, eux,
    permettent de fabriquer une cle qui s'affiche autrement qu'elle ne vaut dans
    un journal ou une console.

    CE QU'ELLE N'IMPOSE PAS
    La forme `{entity_type}/{entity_id}/{nom}`. Une cle relue d'une colonne de
    base a ete ecrite par une version anterieure du service ; lui imposer la
    convention du jour rendrait illisibles des fichiers valides. Composer selon la
    convention est le travail de `build_storage_key`, a l'ECRITURE.

    Args:
        key: la cle a verifier.

    Returns:
        La cle, inchangee -- ce qui laisse ecrire `self._keys(key)` en une ligne
        sur le chemin d'appel.

    Raises:
        InvalidStorageKeyError: si la cle est vide, absolue, contient un segment
            de traversee, un segment vide, un octet de controle, ou depasse la
            longueur admise par le stockage.
    """
    if not key:
        message = "Une cle de stockage ne peut pas etre vide."
        raise InvalidStorageKeyError(message)
    if key.startswith(_SEPARATOR):
        message = f"Une cle de stockage ne peut pas commencer par {_SEPARATOR!r} : {key!r}."
        raise InvalidStorageKeyError(message)
    # `Cc` couvre les caracteres de controle C0 et C1, `Cf` les caracteres de
    # formatage -- dont les marques de sens d'ecriture, avec lesquelles un nom
    # s'affiche a l'envers de ce qu'il vaut. Une categorie Unicode plutot qu'une
    # liste de litteraux : la liste serait fausse le jour ou elle serait ecrite.
    if any(unicodedata.category(char) in {"Cc", "Cf"} for char in key):
        message = f"Une cle de stockage ne peut porter aucun caractere de controle : {key!r}."
        raise InvalidStorageKeyError(message)
    segments = key.split(_SEPARATOR)
    if any(segment in {"", ".", ".."} for segment in segments):
        message = (
            f"Cle de stockage invalide : {key!r}. Un segment vide, `.` ou `..` "
            "permettrait de sortir du prefixe de l'entite."
        )
        raise InvalidStorageKeyError(message)
    # En OCTETS, jamais en caracteres : la borne du stockage porte sur l'encodage
    # UTF-8, ou un accent compte double et un emoji quadruple.
    if len(key.encode("utf-8")) > _MAX_KEY_BYTES:
        message = (
            f"Cle de stockage trop longue : {len(key.encode('utf-8'))} octets pour "
            f"un maximum de {_MAX_KEY_BYTES}."
        )
        raise InvalidStorageKeyError(message)
    return key


def _sanitize_filename(filename: str) -> str:
    """Reduit un nom fourni par l'utilisateur a un segment de cle sur.

    L'ORDRE DES ETAPES EST LE SUJET. Le chemin est retire AVANT le reste : un nom
    valant `../../evasion.pdf` doit devenir `evasion.pdf`, et non
    `------evasion.pdf` -- ce dernier serait inoffensif mais illisible, et
    masquerait dans les journaux ce que l'utilisateur avait reellement envoye.

    RADICAL ET EXTENSION SONT TRAITES SEPAREMENT, et ce n'est pas un rafinement.
    Assainis ensemble, un nom entierement non latin comme `上書き.pdf` perdrait
    son radical ET son point : il resterait `pdf`, une cle ou l'extension a pris
    la place du nom. Separes, il reste `fichier.pdf`, ou le repli se voit pour ce
    qu'il est. Les noms non latins ne sont pas un cas de laboratoire dans un
    service ouvert au public.

    Les accents sont retires plutot que remplaces : `radiographie-thoracique.jpg`
    se lit dans une console, `radiographie-th-oracique.jpg` non.

    Args:
        filename: le nom d'origine.

    Returns:
        Un segment sans chemin, sans accent et sans caractere douteux, borne en
        longueur, et jamais vide.
    """
    # Les deux separateurs, et pas seulement celui du systeme hote : un client
    # Windows envoie `C:\Users\...\photo.jpg`, qu'un `PurePosixPath` laisserait
    # entier.
    base = filename.replace("\\", _SEPARATOR).rsplit(_SEPARATOR, maxsplit=1)[-1]

    # `rpartition` sur le DERNIER point. Un radical vide signifie qu'il n'y avait
    # pas de point du tout, ou que le nom commencait par un -- `.ssh` est un nom,
    # pas une extension.
    stem, _, suffix = base.rpartition(".")
    if not stem or not _looks_like_suffix(suffix):
        stem, suffix = base, ""

    safe_stem = _fold(stem)[:_MAX_FILENAME_LENGTH].strip(".-") or _FALLBACK_FILENAME
    safe_suffix = _fold(suffix)
    return f"{safe_stem}.{safe_suffix}" if safe_suffix else safe_stem


def _looks_like_suffix(candidate: str) -> bool:
    """Dit si ce qui suit le dernier point merite d'etre traite comme extension.

    Args:
        candidate: le fragment situe apres le dernier point.

    Returns:
        Vrai s'il est court et purement alphanumerique. Sinon le nom entier est
        garde comme radical, points compris -- mieux vaut un nom long et fidele
        qu'un nom tronque a un endroit choisi au hasard.
    """
    return bool(candidate) and candidate.isalnum() and len(candidate) <= _MAX_SUFFIX_LENGTH


def _fold(value: str) -> str:
    """Ramene un fragment de nom aux seuls caracteres sans danger.

    Args:
        value: le fragment d'origine -- radical ou extension.

    Returns:
        Le fragment en minuscules, sans accent et sans caractere douteux. Peut
        etre vide : c'est a l'appelant de decider ce qu'il en fait.
    """
    # NFKD separe la lettre de son accent, l'encodage ASCII en `ignore` jette
    # l'accent reste seul. `e` survit, `é` devient `e`, un ideogramme disparait --
    # d'ou le repli de l'appelant, qui rattrape un nom entierement non latin.
    folded = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").casefold()
    )
    safe = _UNSAFE_FILENAME_CHARS.sub("-", folded)
    safe = _REPEATED_SEPARATORS.sub("-", safe)
    # Les points et tirets de tete sont retires : un nom commencant par un point
    # est un fichier cache sur les systemes POSIX, et `..` a deja ete traite par
    # `validate_storage_key` mais n'a aucune raison de pouvoir renaitre ici.
    return safe.strip(".-")
