---
title: Ports et URLs des services
description: L'allocation des ports du dépôt — la garantie d'absence de collision — et les URLs de chaque service.
---

# Ports et URLs des services

Cette page est la source de vérité de l'allocation des ports du dépôt — chaque service y réserve
le sien une fois pour toutes, et les adresses à ouvrir en développement s'y lisent d'un coup d'œil.

Un port par service, réservé une fois pour toutes ici afin qu'aucun ticket n'ait
à en choisir un dans son coin :

| Service                       | Port hôte | Port interne | Arrive avec |
| ----------------------------- | --------- | ------------ | ----------- |
| API FastAPI                   | 8000      | 8000         | disponible  |
| `frontend-professional`       | 3001      | 3000         | disponible  |
| `frontend-individual`         | 3002      | 3000         | disponible  |
| `frontend-admin`              | 3003      | 3000         | disponible  |
| Documentation (Docusaurus)    | 3004      | —            | disponible  |
| PostgreSQL                    | 5432      | 5432         | disponible  |
| pgAdmin                       | 5050      | 80           | disponible  |
| Redis                         | 6379      | 6379         | disponible  |
| RedisInsight (profil `tools`) | 5540      | 5540         | disponible  |
| MinIO — API S3                | 9000      | 9000         | disponible  |
| MinIO — console web           | 9001      | 9001         | disponible  |
| Mailpit — SMTP                | 1025      | 1025         | disponible  |
| Mailpit — boîte de réception  | 8025      | 8025         | disponible  |
| Worker TaskIQ                 | aucun     | —            | disponible  |

Quelques choix méritent leur explication :

- **3000 n'apparaît pas.** C'est le port d'écoute interne des trois conteneurs
  Next.js, jamais publié : INFRA-05b le mappe sur 3001, 3002 et 3003 côté hôte.
  Ce sont donc les mêmes ports qu'en développement local — d'où la règle : ne
  pas lancer `pnpm dev` et `make up` en même temps.
- **pgAdmin sur 5050.** Ni SETUP-05 ni INFRA-01 ne fixaient ce port, et un
  tableau censé garantir l'absence de collision ne peut pas laisser de case
  vide : le choix a été fait ici, et INFRA-01 s'y est tenu. 5050 est le port des
  exemples Compose de pgAdmin — le moins surprenant — et il évite `8080`, déjà
  disputé par trop d'outils, comme les ports 5000 et 7000 que le récepteur
  AirPlay de macOS occupe par défaut.
- **RedisInsight sur 5540**, port d'écoute par défaut de l'image : le publier
  tel quel évite une correspondance de plus à retenir. Le service reste derrière
  le profil Compose `tools` et ne démarre donc pas avec `make up`.
- **Redis, RedisInsight et Mailpit ne sont publiés que sur `127.0.0.1`.** Les
  autres services le sont sur toutes les interfaces du poste ; ces trois-là non.
  Le Redis de développement n'a pas de mot de passe et la console n'a pas de page
  de connexion : les publier largement les offrirait en lecture et en écriture
  à tout le réseau auquel le poste est raccordé — un wifi partagé suffit. Mailpit
  ajoute à cela un relais SMTP qui accepte n'importe quel message de n'importe
  qui, et une boîte où se lisent en clair les codes OTP déjà émis : la règle du
  dépôt tient en une phrase — service sans authentification, boucle locale. Rien
  ne change à l'usage, les URLs et les commandes restent celles de ce tableau.
- **Le worker n'écoute rien.** Il consomme la file Redis et n'ouvre aucun port
  entrant : rien à publier, rien à réserver. `docker compose ps` affiche
  pourtant `8000/tcp` en face de lui — c'est l'`EXPOSE` hérité de l'étage
  `runtime` qu'il partage avec l'API, une métadonnée d'image et rien d'autre :
  aucun port n'est publié, et aucun processus n'écoute. C'est aussi son absence
  de `ports:` qui rend `--scale worker=2` possible.

Les ports publiés sur le poste sont tous **configurables** par une variable
`*_HOST_PORT` du `.env` : un PostgreSQL ou un Redis déjà installé localement se
contourne en changeant une ligne, sans rien toucher aux conteneurs, qui
continuent de se parler sur les ports internes.

Les adresses à ouvrir dans un navigateur :

| Service                         | URL                                                                      | Identifiants                                         |
| ------------------------------- | ------------------------------------------------------------------------ | ---------------------------------------------------- |
| API — documentation interactive | [http://localhost:8000/docs](http://localhost:8000/docs)                 | —                                                    |
| API — contrat OpenAPI           | [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json) | —                                                    |
| API — sonde de disponibilité    | [http://localhost:8000/health/ready](http://localhost:8000/health/ready) | —                                                    |
| `frontend-professional`         | [http://localhost:3001](http://localhost:3001)                           | —                                                    |
| `frontend-individual`           | [http://localhost:3002](http://localhost:3002)                           | —                                                    |
| `frontend-admin`                | [http://localhost:3003](http://localhost:3003)                           | —                                                    |
| Documentation                   | [http://localhost:3004](http://localhost:3004)                           | —                                                    |
| pgAdmin                         | [http://localhost:5050](http://localhost:5050)                           | `PGADMIN_DEFAULT_EMAIL` / `PGADMIN_DEFAULT_PASSWORD` |
| MinIO — console web             | [http://localhost:9001](http://localhost:9001)                           | `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD`            |
| Mailpit — boîte de réception    | [http://localhost:8025](http://localhost:8025)                           | —                                                    |
| RedisInsight                    | [http://localhost:5540](http://localhost:5540)                           | —                                                    |

PostgreSQL et Redis ne parlent pas HTTP : ils s'atteignent par une chaîne de
connexion, que l'API compose elle-même à partir des variables `POSTGRES_*` et
`REDIS_*`. Redis sépare ses usages par base — la base 0 pour le cache
applicatif, la base 1 pour le broker TaskIQ — et RedisInsight les présente comme
deux connexions distinctes, pré-remplies au démarrage.

Les identifiants ne sont pas recopiés ici, seulement nommés : leurs valeurs sont
celles du `.env`, dont `.env.example` porte les exemples de
développement. Une seule source de vérité — un mot de passe écrit à deux
endroits finit toujours par diverger.

Les écarts assumés avec le ticket SETUP-05 sont consignés au
[registre des écarts](../ecarts/setup.md#écarts-assumés-avec-le-ticket-setup-05).
