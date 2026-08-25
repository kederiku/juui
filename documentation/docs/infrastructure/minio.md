---
title: Le stockage objet de développement (MinIO)
description: "Vérifier MinIO : la console, l'aller-retour d'un objet à la main, puis le même vu depuis l'API."
---

# Le stockage objet de développement (MinIO)

MinIO tient lieu d'Amazon S3 sur le poste de développement — même protocole, aucune dépendance au
nuage. Cette page vérifie le service : la console, un aller-retour d'objet à la main, puis le même
vu depuis l'API ; le pendant applicatif — le port de stockage — est décrit dans `backend/api/README.md`.

## Vérifier le stockage objet

MinIO tient lieu d'Amazon S3 sur le poste, et le bucket applicatif — `S3_BUCKET`,
`juui-dev` par défaut — est créé au démarrage par le service éphémère
`minio-init`. Celui-ci s'arrête une fois son travail fait : `docker compose ps`
le montre en `Exited (0)`, ce qui est le résultat attendu et non une panne. Son
journal dit exactement ce qu'il a fait :

```bash
docker compose --project-directory . -f docker/docker-compose.yml logs minio-init
```

La console web s'ouvre sur [http://localhost:9001](http://localhost:9001), avec `MINIO_ROOT_USER` et
`MINIO_ROOT_PASSWORD` pour identifiants. Depuis `RELEASE.2025-05-24T17-08-30Z`,
l'édition communautaire n'y conserve que le **navigateur d'objets** — parcourir
les buckets, téléverser, télécharger, supprimer. Les écrans d'administration
(utilisateurs, politiques, clés d'accès) sont passés à l'édition payante ;
`mc admin` les remplace.

Pour un aller-retour complet sans rien installer sur le poste — le conteneur
`minio-init` a déjà l'endpoint, les identifiants et le nom du bucket dans son
environnement :

```bash
docker compose --project-directory . -f docker/docker-compose.yml run --rm --entrypoint sh minio-init -c 'mc alias set t "$S3_ENDPOINT_URL" "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" && echo bonjour | mc pipe "t/$S3_BUCKET/essai.txt" && mc cat "t/$S3_BUCKET/essai.txt" && mc rm "t/$S3_BUCKET/essai.txt"'
```

Le bucket est **privé** : une requête anonyme sur un objet répond `403`. C'est
délibéré — l'API sert les fichiers par des **URLs pré-signées**, qui portent leur
propre autorisation et expirent, plutôt que par un bucket ouvert en lecture.

## Le même aller-retour, vu depuis l'API

Ce qui précède prouve que MinIO répond ; ceci prouve que le service sait lui
parler. Depuis `backend/api/`, avec un `.env` local — l'API n'a pas besoin de
tourner, le stockage n'étant pas une route :

```bash
uv run python -c "
import asyncio, subprocess
from app.core import get_settings
from app.shared.infrastructure.clients.s3_storage import build_file_storage
s = build_file_storage(get_settings())
async def main():
    print('ping :', await s.ping())
    await s.upload('essai/00000000-0000-7000-8000-000000000000/bonjour.pdf', b'%PDF-1.4', 'application/pdf')
    url = s.generate_presigned_url('essai/00000000-0000-7000-8000-000000000000/bonjour.pdf')
    print('presigne :', subprocess.run(['curl','-s','-o','/dev/null','-w','%{http_code}',url], capture_output=True, text=True).stdout)
    print('supprime :', await s.delete('essai/00000000-0000-7000-8000-000000000000/bonjour.pdf'))
asyncio.run(main())
"
```

Attendu : `ping : True`, `presigne : 200`, `supprime : True`. La même URL sans sa
signature — tout ce qui suit le `?` retiré — répond `403` : c'est la signature qui
autorise, jamais le bucket.

Les six sondes complètes du stockage, l'expiration réelle d'une URL et le
comportement du service quand MinIO est éteint sont dans le
[README de `backend/api/`](https://github.com/kederiku/juui/blob/main/backend/api/README.md#vérifier-que-le-stockage-tient).

Les écarts assumés avec le ticket INFRA-03 sont consignés au
[registre des écarts](../ecarts/infra.md#écarts-assumés-avec-le-ticket-infra-03).
