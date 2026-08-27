"""Adaptateurs de securite : ce qui signe, verifie et protege des secrets.

La place que BACK-04 avait reservee ici, et que la docstring du paquet parent
annoncait. Un sous-paquet distinct de `clients/` parce que ces adaptateurs ne
parlent a AUCUN service externe : ils calculent. Un jeton se signe et se verifie
en memoire, sans socket a ouvrir au demarrage ni a refermer a l'arret -- il n'y
a donc ni ressource dans `app.state`, ni accesseur, et la fabrique suffit.

CE QUE CHAQUE TICKET APPORTE ICI

| Fichier          | Port             | Ticket   |
| ---------------- | ---------------- | -------- |
| `jwt_service.py` | `TokenService`   | BACK-10a |
| `password.py`    | `PasswordHasher` | BACK-10b |

BACK-10b a rejoint ce paquet avec le hachage argon2id, qui a bien la propriete
annoncee : du calcul, pas de reseau. Il en revele cependant une limite du
raisonnement ci-dessus -- « pas de reseau » ne veut pas dire « gratuit ». Un
hachage coute une quinzaine de millisecondes de processeur PUR et plusieurs
mebioctets, si bien que l'adaptateur doit sortir son calcul de la boucle
d'evenements comme un adaptateur reseau sort son attente. Ce qui distingue ce
paquet de `clients/`, c'est donc ce qu'il n'a pas a OUVRIR ni a REFERMER, pas le
fait qu'il ne coute rien.

Le controle de fuite de mot de passe (BACK-10b) ne vit PAS ici, malgre le sujet :
il parle a un service externe, et il est range dans `clients/` avec les autres.
"""
