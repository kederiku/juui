---
title: Le SMTP de développement (Mailpit)
description: "Vérifier Mailpit : la boîte de réception locale, l'envoi d'un courrier de test, et pourquoi rien ne sort du poste."
---

# Le SMTP de développement (Mailpit)

Mailpit est le serveur SMTP factice de la pile Docker locale — il capture chaque courrier émis par
l'application et n'en laisse jamais sortir un seul du poste. Cette page explique comment vérifier
son bon fonctionnement, de la boîte web jusqu'à l'aller-retour complet envoi/relecture.

Mailpit tient lieu de fournisseur d'envoi sur le poste : il **accepte** tout et
n'**expédie** rien. Sans lui, le parcours d'inscription s'arrêtait définitivement
à l'écran de saisie du code OTP — l'e-mail partait, personne ne le lisait, et le
compte restait non vérifié.

La boîte de réception s'ouvre sur [http://localhost:8025](http://localhost:8025), sans identifiants.
Elle est **vide à chaque démarrage**, et c'est voulu : le service n'a aucun
volume, donc le dernier message affiché est toujours celui qu'on vient de
déclencher. `make mail` l'ouvre directement — et sur un poste sans navigateur,
la cible affiche l'URL au lieu d'échouer.

Pour un aller-retour complet — envoi sur le port SMTP, relecture par l'API HTTP —
depuis le conteneur `api`, c'est-à-dire par le chemin exact qu'empruntera
l'adaptateur de BACK-22. `smtplib` et `urllib` sont dans la bibliothèque standard
de Python : il n'y a rien à installer, et l'image `python:3.14-slim` n'a de toute
façon ni `curl` ni `wget`.

```bash
docker compose --project-directory . -f docker/docker-compose.yml exec api python -c "
import json, smtplib, urllib.request
from email.message import EmailMessage
m = EmailMessage()
m['From'], m['To'], m['Subject'] = 'no-reply@juui.test', 'essai@juui.test', 'INFRA-07'
m.set_content('Code de verification : 123456')
with smtplib.SMTP('mailpit', 1025) as s: s.send_message(m)
r = json.load(urllib.request.urlopen('http://mailpit:8025/api/v1/messages'))
print(r['messages'][0]['Subject'], '--', r['messages'][0]['Snippet'])
"
```

La commande affiche `INFRA-07 -- Code de verification : 123456`, et le message
apparaît dans la boîte web. Si le service `api` n'est pas démarré, la même
vérification tient entièrement dans le conteneur Mailpit, qui embarque un
`sendmail` et dont l'image Alpine fournit `wget` :

```bash
docker compose --project-directory . -f docker/docker-compose.yml exec mailpit sh -c 'printf "Subject: INFRA-07\n\nCode : 123456\n" | /mailpit sendmail -f no-reply@juui.test -S 127.0.0.1:1025 essai@juui.test && wget -qO- http://127.0.0.1:8025/api/v1/messages'
```

**L'API HTTP est la seule manière prévue de récupérer un code OTP dans un test.**
`GET /api/v1/messages` liste la boîte, `GET /api/v1/message/{id}` rend le corps
complet, `GET /api/v1/search` filtre par destinataire et `DELETE /api/v1/messages`
la vide entre deux cas. La documentation interactive est servie par l'instance
elle-même, sur [http://localhost:8025/api/v1/](http://localhost:8025/api/v1/).

C'est ce que feront BACK-17 et l'helper de lecture d'e-mails de QA-04 : lire le
code **réellement émis**, plutôt que d'aller le chercher dans Redis. Un test qui
lit Redis vérifie ce que le code a écrit ; il passerait au vert avec un envoi
cassé, une adresse erronée ou un gabarit vide.

:::note L'adaptateur SMTP appartient à BACK-22
Ce ticket ne livre que l'infrastructure — le service, ses variables,
sa sonde et cette page. L'adaptateur SMTP qui consommera `SMTP_HOST`,
`SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_USE_TLS` et `MAIL_FROM`
appartient à BACK-22, et ces six variables ne sont pas encore passées au
service `api` : le fichier compose porte le bloc, en commentaires, à l'endroit
où BACK-22 le décommentera.
:::

Les écarts assumés avec le ticket INFRA-07 sont consignés au
[registre des écarts](../ecarts/infra.md#écarts-assumés-avec-le-ticket-infra-07).
