"""Doublures en memoire des ports partages -- les Fakes du projet (BACK-06c).

Le guide DDD du projet privilegie explicitement les FAKES aux MOCKS, et ce
paquet est ce que cette phrase coute : des implementations COMPLETES des ports,
adossees a des dictionnaires, qui rendent les tests de cas d'usage rapides et
deterministes sans Docker ni base de donnees.

CE QU'UNE DOUBLURE DOIT A SON PORT
Tout. Une fake dont le `rollback()` ne fait rien valide une semantique que la
vraie implementation ne tient pas -- c'est PIRE que pas de test, parce qu'un test
vert affirme quelque chose. La regle de ce paquet tient donc en une ligne : ce
qu'un test observe ici, il doit l'observer a l'identique en production. Le filtre
de tenance est reproduit, les ecritures sont mises en attente jusqu'au commit,
les erreurs d'absence sont celles du module, et le cache compose ses cles avec le
VRAI compositeur.

CE QUI GARANTIT QUE CELA RESTE VRAI
Rien, dans du code -- seulement un test. `tests/shared/conformance/` execute une
MEME suite contre l'implementation reelle et contre la doublure : c'est le seul
mecanisme qui empeche les deux de deriver l'une de l'autre au fil des tickets, et
la raison pour laquelle une doublure qui gagne un comportement doit gagner sa
ligne de conformite dans le meme commit.

CE QUE LES DOUBLURES NE REPRODUISENT PAS, ET NE DOIVENT PAS REPRODUIRE
Les contraintes du STOCKAGE : unicite d'une adresse, cle etrangere, NOT NULL,
verrou, ordre des NULL dans un tri. Les inventer ici serait mentir dans l'autre
sens -- une fake qui refuse ce que PostgreSQL accepterait fait echouer un test
pour rien. Ces proprietes-la sont l'objet des tests d'INFRASTRUCTURE sur vraie
base, troisieme niveau de la strategie de BACK-12, et d'eux seuls.

POURQUOI CE PAQUET VIT DANS `src/` ET NON DANS `tests/`
C'est la portee litterale du ticket, la place que `shared/infrastructure/`
reservait depuis BACK-04, et un choix consigne en ADR-0023. En deux mots : une
doublure rangee sous `tests/` n'est importable que par les tests du meme
paquet -- or `InMemoryCache` sert aux tests d'`identity` comme a ceux de
`medical_records`, et une sonde de documentation ne peut rien importer de
`tests/` du tout. Contrepartie assumee : ces classes voyagent dans la roue de
production.

CE QUI EST ICI, ET CE QUI N'Y EST PAS
Ici : les doublures des ports de `shared/domain/ports/` -- unite de travail,
depots, cache, stockage objet, transport de courriel, controle de fuite. Pas
ici : les doublures des ports METIER (`FakeOtpSender`, `FakeNotificationSender`),
qui vivent dans `infrastructure/memory/` de LEUR module. Ce n'est pas un gout de
rangement : le contrat `service-spaces` interdit a `app.shared` d'importer
`app.modules`, et un `FakeOtpSender` pose ici ferait echouer `make lint`.
"""
