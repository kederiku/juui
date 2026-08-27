"""Contextes metier du service, chacun etanche vis-a-vis des autres.

Un module regroupe les trois couches hexagonales -- `domain/`, `application/`,
`infrastructure/` -- AUTOUR D'UN METIER, et non l'inverse. Le decoupage par
couche seule produit un `domain/entities/` ou quarante entites s'empilent sans
qu'aucune frontiere ne dise laquelle repond a quelle question.

LA REGLE D'INDEPENDANCE
Un module n'importe JAMAIS l'interieur d'un autre module. Ni son entite, ni son
depot, ni son modele de persistance, ni une jointure sur ses tables. Les
echanges passent par les CAS D'USAGE PUBLICS du module cible -- c'est-a-dire par
la surface qu'il a choisi d'exposer, et qu'il peut donc tenir dans le temps.

Exemple deja arbitre : la liste d'administration des comptes particuliers
(BACK-26) affiche un nombre d'animaux. Ce compteur vient du cas d'usage public
de `medical_records` (BACK-30), jamais d'un `JOIN` sur ses tables.

Le contrat `module-independence` de BACK-04b rend cette regle mecanique : une
violation echoue en CI, elle ne se decouvre pas six mois plus tard en revue. Il
suit les CHAINES d'imports, dans les deux sens -- passer par `app.shared` pour
atteindre un autre module ne le contourne pas. Sa declaration, et celle des
quatre autres contrats, est dans pyproject.toml, section [tool.importlinter].

LE PIEGE A EVITER
Ne PAS calquer les modules sur les trois frontends (professional, individual,
admin). Ce sont des canaux de livraison, pas des contextes metier : le coeur
d'authentification -- hachage, OTP, 2FA, session, revocation -- y est identique,
et le triplerait a l'identique. Le type de compte est une PROPRIETE du compte,
porte par `identity` ; l'audience du jeton (BACK-10a) est ce qui separe les trois
applications.

LES MODULES

| Module            | Question a laquelle il repond                   | Ticket   |
| ----------------- | ----------------------------------------------- | -------- |
| `identity`        | peux-tu prouver qui tu es                       | BACK-04  |
| `organization`    | dans quelle structure travailles-tu, affecte ou | BACK-16  |
| `medical_records` | de quels animaux s'agit-il                      | BACK-19  |
| `scheduling`      | quand, avec qui, pour quel acte                 | BACK-21  |
| `notifications`   | qui prevenir, par quel canal                    | BACK-22  |
| `profile`         | ou habite ce particulier                        | BACK-32  |

`identity` est le module PILOTE de BACK-04 : il est le seul complet a ce stade,
et sert de reference de structure aux suivants.

`notifications` (BACK-22) est le premier a avoir eprouve la regle d'independance
pour de bon, et sa reponse fait jurisprudence. Deux modules avaient besoin du
meme dialogue SMTP ; ni l'un ni l'autre ne pouvait importer l'autre. Le besoin
TECHNIQUE est donc descendu dans `shared/domain/ports/`, ou les deux
l'atteignent sans se connaitre (ADR-0022) -- et non l'inverse, qui aurait fait
du premier arrive une dependance du second. Ce que `notifications` garde pour
lui est ce qui parle METIER : les evenements, les preferences, le choix du canal.

`scheduling` (BACK-21) a eprouve l'AUTRE moitie de la meme regle, et sa reponse
est le pendant exact de la precedente. Deux modules avaient besoin du meme
VOCABULAIRE -- l'espece d'un animal chez `medical_records`, l'espece prise en
charge par un praticien ici -- et le meme contrat leur interdisait de
s'importer. Un vocabulaire metier ne descend PAS dans `shared/`, reserve au
besoin technique : il se RECOPIE, et une garde de non-derive le tient
(ADR-0026). Le precedent etait deja pose par BACK-10a, qui a recopie les trois
types de compte d'identity plutot que d'en faire descendre l'enum. La regle a
retenir tient en une phrase : le besoin TECHNIQUE partage descend, le
VOCABULAIRE metier partage se duplique et se garde.
"""
