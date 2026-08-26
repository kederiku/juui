---
title: Stockage objet
description: "Le port de stockage S3/MinIO : les clés, les URLs pré-signées et l'asymétrie en trois temps du service."
---

# Stockage objet

Photos d'animaux, comptes rendus, documents de santé — tout fichier de Juui vit dans un bucket S3,
tenu par MinIO sur le poste et par Amazon S3 en production. Cette page décrit le port `FileStorage`,
sa convention de clés et ses URLs pré-signées ; le service MinIO côté infrastructure a sa propre
page : [MinIO](../infrastructure/minio.md).

Les fichiers — photos d'animaux, comptes rendus, documents de santé — vivent dans un **bucket S3**.
MinIO en tient lieu sur le poste, Amazon S3 en production, et **un seul paramètre les distingue** :
`S3_ENDPOINT_URL`. Rempli, boto3 parle à MinIO ; vide, il retombe sur les endpoints Amazon calculés
depuis la région. Aucune ligne de code ne connaît le mot « MinIO ».

Le domaine ne connaît que le port `FileStorage`. L'adaptateur, la convention de clés et la
construction du client vivent dans `shared/infrastructure/` — même contrainte qu'au
[cache](./cache.md) : `domain-purity` refuse au domaine `boto3`, `botocore` et les chaînes indirectes,
`app.core` compris.

## Le port, et ce qu'il promet

Cinq opérations : `upload`, `download`, `delete`, `exists`, `generate_presigned_url`. Quatre règles
les accompagnent, écrites dans la docstring de `FileStorage`.

**1. Aucune dégradation, jamais.** C'est le point où ce port s'oppose au précédent, et la
question s'est reposée au suivant — l'[unité de travail](./unite-de-travail.md) y répond en levant
**et** en annulant. `Cache` rend `MISSING` quand Redis tombe, parce qu'un
cache absent ne change qu'une **latence**. Un stockage absent change un **résultat** :

- un `upload` qui ne lèverait pas serait un fichier **perdu**, alors qu'on vient de répondre
  « enregistré » à l'utilisateur ;
- un `exists` qui rendrait `False` sur panne déclarerait **inexistant** un document de santé qui
  existe.

Aucune des cinq opérations n'a donc de valeur de repli. `exists()` contient le seul `except` du
fichier qui avale une erreur, et il n'avale que `StoredFileNotFoundError` — la panne, elle, continue
de remonter. C'est ce qui sépare « ce document n'existe pas » de « je ne sais pas s'il existe ».

**2. Les clés sont complètes, et validées.** Contrairement aux clés de cache, qui sont _logiques_ et
que l'adaptateur préfixe, une clé de stockage est celle qui sera **persistée en base**.

**3. Le cloisonnement entre groupes n'est pas dans le nommage.** Voir plus bas.

**4. La validation précède le réseau.** `UploadPolicy` — 20 Mio, et `image/jpeg`, `image/png`,
`image/webp`, `application/pdf` — s'applique avant le premier octet émis, et le type est vérifié
**avant** la taille : un fichier de 40 Mo au format refusé doit s'entendre dire que le format est
refusé, pas partir se faire compresser en vain.

La politique vit dans le **port** et non dans l'adaptateur : « quels fichiers ce service
accepte-t-il ? » ne dépend ni de S3, ni du fournisseur suivant. `image/heic` n'y figure pas, et
c'est une lacune **connue** — c'est le format natif des photos d'iPhone, et l'accepter sans
conversion côté serveur produirait des fichiers que ni les navigateurs ni les visionneuses de bureau
n'affichent.

Six exceptions, toutes sous `FileStorageError`, elle-même sous `DomainError` :
`StoredFileNotFoundError`, `FileTooLargeError`, `UnsupportedContentTypeError`,
`InvalidStorageKeyError`, `FileStorageUnavailableError`. **Aucune exception boto3 n'en sort** —
`_call` est le seul endroit du service qui connaisse `ClientError`, et c'est ce qui permet à un cas
d'usage d'attraper `FileStorageError` sans importer la bibliothèque du fournisseur.

:::note Nommage de l'exception

`StoredFileNotFoundError` et non `FileNotFoundError` : la règle Ruff `A` refuse de masquer un
builtin. L'écart de nom vaut mieux qu'une classe qui, attrapée par mégarde, avalerait aussi les
erreurs du système de fichiers local.

:::

## La clé, et ce qu'elle ne porte pas

```
{entity_type}/{entity_id}/{nom de fichier assaini}
```

Par exemple `animal-photos/01931f2a-…/radiographie-thoracique.jpg`. Le segment central est un UUID :
deux téléversements du même nom ne peuvent pas se confondre.

`build_storage_key` **compose** une clé conforme ; `validate_storage_key` vérifie qu'une clé est
**sans danger**, sans lui imposer cette forme. La distinction n'est pas théorique : une clé relue
d'une colonne de base a été composée par une version antérieure du service, et la refuser sur un
changement de convention rendrait illisibles des fichiers parfaitement valides. Ce qui est refusé
sans discussion, c'est ce qui **sort de son préfixe** — `..`, barre initiale, segment vide, caractère
de contrôle, clé de plus de 1024 octets.

L'assainissement du nom traite le **radical et l'extension séparément**, et ce n'est pas un
raffinement : assainis ensemble, `上書き.pdf` perdrait son radical _et_ son point, et il resterait
`pdf` — une clé où l'extension a pris la place du nom. Séparés, il reste `fichier.pdf`, où le repli
se voit pour ce qu'il est. Un nom entièrement non latin n'est pas un cas de laboratoire dans un
service ouvert au public.

| Nom fourni                              | Clé produite                            |
| --------------------------------------- | --------------------------------------- |
| `Radiographie Thoracique.JPG`           | `radiographie-thoracique.jpg`           |
| `../../evasion.pdf`                     | `evasion.pdf`                           |
| `C:\Users\moi\échographie (2).png`      | `echographie-2.png`                     |
| `上書き.pdf`                            | `fichier.pdf`                           |
| `rapport.2026.sauvegarde-du-15-janvier` | `rapport.2026.sauvegarde-du-15-janvier` |

Le dernier montre la règle : ce qui suit le dernier point n'est traité comme extension que s'il est
court et purement alphanumérique. Sinon le nom entier est gardé — mieux vaut un nom long et fidèle
qu'un nom tronqué à un endroit choisi au hasard.

**Aucun segment de tenance, et c'est délibéré.** Une clé de cache est volatile ; une clé de stockage
est persistée. La faire dépendre de `current_group_id` la rendrait introuvable dès que le contexte de
lecture diffère de celui de l'écriture — une tâche de fond (BACK-15), un export, ou simplement un
vétérinaire remplaçant qui a changé de structure entre-temps. Le cloisonnement entre groupes
appartient à l'**autorisation** : qui a le droit de demander une URL pré-signée pour cette clé. Il ne
peut pas appartenir au nommage d'une donnée durable.

:::warning Corollaire à ne jamais oublier

**L'opacité d'un UUID n'est pas un contrôle d'accès.** Le bucket est privé (INFRA-03 le referme à
chaque démarrage), et c'est la route qui émet l'URL pré-signée qui devra vérifier le droit d'y
accéder.

:::

Pas de préfixe d'environnement non plus, contrairement aux clés de cache : les environnements ont des
**buckets** distincts, la séparation est faite un cran au-dessus.

## Les URLs pré-signées sont la voie principale

Une URL pré-signée porte son autorisation et son expiration dans sa signature : le navigateur parle
**directement** au stockage, et l'octet du fichier ne traverse jamais l'API. Faire transiter les
fichiers par les workers reviendrait à occuper une boucle d'événements entière pendant le
téléversement d'une radiographie.

`generate_presigned_url` est la seule des cinq opérations à être **synchrone**, et c'est ce qui rend
ce chemin gratuit : signer n'appelle personne, botocore calcule une empreinte à partir de la clé
secrète, de la date et du verbe. Elle fonctionne même stockage éteint.

Quinze minutes par défaut, `expires_in` par appel, plafond de sept jours — celui de la signature V4,
au-delà duquel le stockage refuserait l'URL sans en dire la raison.

**Une URL de téléversement exige son type MIME.** Sans lui, le chemin principal échapperait
entièrement à `UploadPolicy` : l'API n'est plus sur le trajet pour regarder ce qui passe. Le type est
donc validé, puis **épinglé dans la signature** — un dépôt qui annonce autre chose est refusé par le
stockage lui-même, avec un `403`. Le rendre facultatif aurait fait de la validation une politesse.

:::warning Pas de plafond de taille

**Ce qu'une URL de téléversement ne peut toujours pas faire : plafonner la taille.** Un PUT
pré-signé n'emporte aucune condition sur la longueur du corps, et il n'existe aucun moyen de lui en
ajouter — seul un **formulaire** pré-signé (POST, avec une condition `content-length-range` dans sa
policy) l'exprimerait. `max_bytes` ne s'applique donc qu'à `upload`. Le ticket qui exposera la route
de téléversement direct devra le savoir, et passer au formulaire pré-signé s'il tient à la borne.

:::

**Limite d'exploitation.** L'URL porte l'**hôte** de `endpoint_url`. Dans la pile Docker, c'est
`http://minio:9000`, résolvable depuis `app_network` seulement : une URL émise par l'API en conteneur
n'est pas ouvrable depuis le navigateur du poste. Sans conséquence tant qu'aucune route ne la publie ;
le ticket qui exposera ces URLs au frontend devra distinguer l'endpoint **interne** de l'endpoint
**public** — ce que BACK-13 écarte, ayant posé qu'un seul paramètre sépare MinIO d'Amazon.

## L'asymétrie du service a trois temps, pas deux

C'est la question à se poser en branchant la ressource suivante dans le `lifespan`.

| Ressource      | Au démarrage                     | À l'appel                        | Pourquoi                                            |
| -------------- | -------------------------------- | -------------------------------- | --------------------------------------------------- |
| PostgreSQL     | **lève** (`verify_connectivity`) | lève                             | sans base, aucune route ne répond juste             |
| Redis          | journalise                       | **dégrade** (`MISSING`, `False`) | sans cache, toutes répondent — plus lentement       |
| Stockage objet | journalise                       | **lève**                         | sans bucket, seules les routes de fichiers échouent |

Le stockage est le seul des trois à se comporter différemment au démarrage et à l'appel. Refuser de
partir priverait le service de tout ce qui n'a rien à voir avec les fichiers ; se taire à l'appel
ferait perdre des fichiers en silence. `ping()` journalise, les opérations lèvent — et
l'avertissement part en `WARNING`, au format posé par BACK-11
([Journalisation](./journalisation.md)).

## Vérifier que le stockage tient

Six sondes. La première ne demande **aucun** conteneur.

**1. La convention de clés et la politique d'upload — sans réseau.**

```bash
uv run python - <<'PY'
from uuid import UUID
from app.shared.domain.ports.file_storage import (
    DEFAULT_UPLOAD_POLICY, FileTooLargeError, InvalidStorageKeyError,
    UnsupportedContentTypeError,
)
from app.shared.infrastructure.clients.storage_keys import build_storage_key, validate_storage_key

ANIMAL = UUID("01931f2a-0000-7000-8000-00000000000a")

print("--- composition ---")
for nom in ("Radiographie Thoracique.JPG", "../../evasion.pdf",
            "C:\\Users\\moi\\échographie (2).png", "上書き.pdf", ".ssh"):
    print(f"  {nom!r:44} -> {build_storage_key('animal-photos', ANIMAL, nom).rsplit('/', 1)[-1]}")

print("--- cles refusees ---")
for cle in ("", "/absolu.jpg", "a/../../b.jpg", "a//b.jpg", "a/b\u202e.jpg", "x/" + "a" * 1030):
    try:
        validate_storage_key(cle)
        print(f"  {cle[:28]!r:32} -> ACCEPTEE  <<< PROBLEME")
    except InvalidStorageKeyError as erreur:
        print(f"  {cle[:28]!r:32} -> refusee : {str(erreur)[:56]}")

print("--- politique d'upload ---")
politique = DEFAULT_UPLOAD_POLICY
for octets, type_mime in ((b"x", "image/svg+xml"),
                          (b"x" * (politique.max_bytes + 1), "image/png"),
                          (b"x", "image/png")):
    try:
        politique.validate(octets, type_mime)
        print(f"  {len(octets):>9} o {type_mime:<14} -> accepte")
    except (UnsupportedContentTypeError, FileTooLargeError) as erreur:
        print(f"  {len(octets):>9} o {type_mime:<14} -> {type(erreur).__name__}")
PY
```

Attendu : `../../evasion.pdf` devient `evasion.pdf`, `上書き.pdf` devient `fichier.pdf`, les six clés
sont refusées, et seul le `image/png` d'un octet passe la politique.

Les cinq suivantes demandent la pile (`make up`) et un `.env` local pointant `localhost:9000`.

**2. L'aller-retour complet des cinq opérations.**

```bash
uv run python - <<'PY'
import asyncio, subprocess, time
from uuid import UUID

from app.core import get_settings
from app.shared.domain.ports.file_storage import PresignedOperation, StoredFileNotFoundError
from app.shared.infrastructure.clients.s3_storage import build_file_storage
from app.shared.infrastructure.clients.storage_keys import build_storage_key

ANIMAL = UUID("01931f2a-0000-7000-8000-00000000000a")


def statut(url: str) -> str:
    """Code HTTP rendu par un GET nu sur l'URL."""
    return subprocess.run(
        ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", url],
        capture_output=True, text=True, check=True,
    ).stdout


async def main() -> None:
    stockage = build_file_storage(get_settings())
    print("cible :", stockage.target, "| ping :", await stockage.ping())

    cle = build_storage_key("animal-photos", ANIMAL, "Radiographie Thoracique.JPG")
    await stockage.upload(cle, b"\xff\xd8\xff-fausse-image", "image/jpeg")
    print("upload   -> exists :", await stockage.exists(cle))
    print("download ->", await stockage.download(cle))

    url = stockage.generate_presigned_url(cle)
    print("presign GET -> curl :", statut(url))

    court = stockage.generate_presigned_url(cle, expires_in=1)
    print("expire=1s : immediat", statut(court), end=" ")
    time.sleep(2)
    print("| apres 2s", statut(court))

    print("delete ->", await stockage.delete(cle), "| re-delete ->", await stockage.delete(cle))
    try:
        await stockage.download(cle)
        print("download apres delete -> AUCUNE ERREUR  <<< PROBLEME")
    except StoredFileNotFoundError:
        print("download apres delete -> StoredFileNotFoundError")
    await stockage.aclose()


asyncio.run(main())
PY
```

Attendu :

```
cible : http://localhost:9000/juui-dev | ping : True
upload   -> exists : True
download -> b'\xff\xd8\xff-fausse-image'
presign GET -> curl : 200
expire=1s : immediat 200 | apres 2s 403
delete -> True | re-delete -> False
download apres delete -> StoredFileNotFoundError
```

Les deux dernières lignes portent trois critères d'acceptation à elles seules : l'aller-retour,
l'expiration réelle de l'URL — `200` puis `403`, pas une lecture de code — et un `delete` dont le
retour ne ment pas.

**3. Le type MIME épinglé dans la signature d'un téléversement.** C'est ce qui empêche le chemin
direct d'échapper à la politique.

```bash
uv run python - <<'PY'
import asyncio, subprocess
from uuid import UUID

from app.core import get_settings
from app.shared.domain.ports.file_storage import PresignedOperation, UnsupportedContentTypeError
from app.shared.infrastructure.clients.s3_storage import build_file_storage
from app.shared.infrastructure.clients.storage_keys import build_storage_key

ANIMAL = UUID("01931f2a-0000-7000-8000-00000000000b")


def depose(url: str, type_mime: str) -> str:
    """Code HTTP rendu par un PUT annoncant ce type."""
    return subprocess.run(
        ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "-X", "PUT",
         "-H", f"Content-Type: {type_mime}", "--data-binary", "%PDF-1.4 faux", url],
        capture_output=True, text=True, check=True,
    ).stdout


async def main() -> None:
    stockage = build_file_storage(get_settings())
    cle = build_storage_key("medical-documents", ANIMAL, "compte rendu.pdf")
    url = stockage.generate_presigned_url(
        cle, operation=PresignedOperation.UPLOAD, content_type="application/pdf"
    )
    print("PUT, bon type     ->", depose(url, "application/pdf"), "| exists :",
          await stockage.exists(cle))
    print("PUT, MAUVAIS type ->", depose(url, "image/png"))
    await stockage.delete(cle)

    try:
        stockage.generate_presigned_url(
            cle, operation=PresignedOperation.UPLOAD, content_type="application/x-msdownload"
        )
        print("type hors politique -> ACCEPTE  <<< PROBLEME")
    except UnsupportedContentTypeError:
        print("type hors politique -> UnsupportedContentTypeError")

    for arguments in ({"operation": PresignedOperation.UPLOAD}, {"expires_in": 0},
                      {"expires_in": 10**7}, {"content_type": "image/png"}):
        try:
            stockage.generate_presigned_url(cle, **arguments)
            print(f"  {arguments} -> ACCEPTE  <<< PROBLEME")
        except ValueError as erreur:
            print(f"  {str(arguments)[:32]:34} -> ValueError : {str(erreur)[:44]}")
    await stockage.aclose()


asyncio.run(main())
PY
```

Attendu : `200` avec le bon type, **`403` avec un autre** — c'est MinIO qui refuse, pas l'API —, puis
quatre `ValueError` : un téléversement sans type, une expiration nulle, une expiration au-delà de sept
jours, et un type MIME donné à un téléchargement.

**4. Le stockage injoignable : le service démarre, les opérations lèvent.**

```bash
S3_ENDPOINT_URL=http://127.0.0.1:9 uv run python - <<'PY'
import asyncio

from app.core import get_settings
from app.shared.domain.ports.file_storage import FileStorageUnavailableError
from app.shared.infrastructure.clients.s3_storage import build_file_storage


async def main() -> None:
    stockage = build_file_storage(get_settings())
    print("ping ->", await stockage.ping(), "(False, SANS lever : le service demarre)")
    for nom, appel in (
        ("upload", stockage.upload("x/y/z.png", b"x", "image/png")),
        ("download", stockage.download("x/y/z.png")),
        ("exists", stockage.exists("x/y/z.png")),
        ("delete", stockage.delete("x/y/z.png")),
    ):
        try:
            await appel
            print(f"  {nom:9} -> AUCUNE ERREUR  <<< PROBLEME")
        except FileStorageUnavailableError:
            print(f"  {nom:9} -> FileStorageUnavailableError")
    print("  presign   ->", stockage.generate_presigned_url("x/y/z.png")[:44], "(hors ligne)")
    await stockage.aclose()


asyncio.run(main())
PY
```

Attendu : un `WARNING` nommant l'endpoint, `ping` à `False`, **quatre** levées — `exists` compris,
qui ne se rabat pas sur `False` — et une URL signée malgré tout, la signature étant un calcul local.
C'est le tableau de l'asymétrie, observé plutôt que lu.

**5. Basculer sur Amazon S3 ne demande qu'une configuration.** Vérifiable sans compte AWS :

```bash
S3_ENDPOINT_URL= uv run python -c "
from app.core import get_settings
from app.shared.infrastructure.clients.s3_storage import build_file_storage
stockage = build_file_storage(get_settings())
print('target :', stockage.target)
print('URL    :', stockage.generate_presigned_url('animal-photos/x/y.jpg').split('?')[0])
"
```

Attendu : `target : Amazon S3/juui-dev` et une URL sur `https://s3.amazonaws.com`. Une variable
vidée, **pas une ligne de code**.

**6. Le cycle de vie, et l'ordre de démarrage de la pile.**

```bash
docker compose --project-directory . -f docker/docker-compose.yml up -d api
```

Attendu, dans la sortie : `minio Healthy`, puis `minio-init Started`, puis **`minio-init Exited`**,
et seulement ensuite `api Started`. C'est le `depends_on: service_completed_successfully` qui
l'impose — un bucket dont la création a échoué empêche l'API de partir, au lieu de la laisser
découvrir l'absence au premier téléversement.

Les écarts assumés avec le ticket BACK-13 sont consignés au
[registre des écarts](../ecarts/back.md#écarts-assumés-avec-le-ticket-back-13).
