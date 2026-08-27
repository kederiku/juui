---
title: 'ADR-0026 — La fiche technique du praticien est portée par la clinique, déclarée en heure murale, et son vocabulaire se duplique'
description: "Horaires et espèces d'un praticien sortent d'identity, se rattachent au couple (compte, clinique) dans un groupe, se disent en minutes d'horloge murale, et empruntent à medical_records un catalogue d'espèces recopié plutôt que partagé."
---

# ADR-0026 — La fiche technique du praticien est portée par la clinique, déclarée en heure murale, et son vocabulaire se duplique

| Statut      | Date       | Tickets                                      |
| ----------- | ---------- | -------------------------------------------- |
| **Accepté** | 2026-08-27 | BACK-21, BACK-16, BACK-19, BACK-32 (à venir) |

## Contexte

Décision rendue par BACK-21, qui pose le module `scheduling`.

La page « mon compte » du cahier des charges affiche, dans un seul écran, le nom et le mot de passe,
l'adresse postale, **les horaires d'intervention et les espèces prises en charge**, les préférences
de notification et les fiches animaux. Une page, cinq contextes. Modélisée telle qu'elle s'affiche,
elle produit la table des comptes à trente colonnes dont vingt-cinq nulles selon le type de compte —
le fourre-tout que le découpage en modules ([ADR-0003](./0003-monolithe-modulaire.md)) existe pour
éviter.

Sortir horaires et espèces d'`identity` posait ensuite trois questions, dont aucune n'avait de
réponse évidente qui tienne à l'examen.

**Qui porte la fiche ?** Le réflexe est le compte : un praticien, une fiche. Il ne survit pas au
vétérinaire remplaçant, qui intervient dans plusieurs structures avec un seul compte et n'y a ni les
mêmes horaires ni forcément les mêmes espèces. La carte du ticket dit « portée par l'**affectation**
à une clinique » — mais les affectations appartiennent au module `organization`, et
l'[ADR-0015](./0015-cles-etrangeres-frontiere-module.md) interdit la clé étrangère qui traverserait
la frontière.

**Que veut dire « 09:00 » ?** Rien, dans l'absolu. Une heure d'ouverture est une heure **murale**,
lue au mur de la clinique. La convertir en instant absolu suppose de connaître un fuseau que ce
module ne possède pas.

**Comment nommer une espèce ?** `medical_records` a déjà un catalogue fermé d'espèces
([ADR-0006](./0006-dossier-medical-animal.md)), et le contrat `module-independence` interdit à
`scheduling` de l'importer — directement comme par chaîne.

## Décision

**La fiche vit dans `scheduling`, pas dans `identity`.** Des horaires d'intervention sont une
**disponibilité** ; des espèces prises en charge sont une **compétence**, celle qui appariera un
praticien et un animal. Les deux sont consommées par la prise de rendez-vous, jamais par
l'authentification. Que le formulaire vive dans « mon compte » est une décision d'IHM, pas une
décision de modèle.

**Elle est portée par le couple `(compte, clinique)` à l'intérieur d'un groupe.** « Portée par
l'affectation » se lit **coordonnées de l'affectation**, pas identité de l'affectation : une
affectation est datée et se renouvelle, une fiche pendue à son identifiant deviendrait orpheline à
chaque contrat. `account_id` et `clinic_id` restent des identifiants **nus** — aucune clé étrangère
ne franchit la frontière d'un module.

**Une seule contrainte de schéma sert quatre besoins, et l'ordre de ses colonnes est porteur.**
`UniqueConstraint("group_id", "clinic_id", "account_id")` satisfait à la fois la garde d'index de
`TenantMixin` (qui n'exige que la première colonne, et compte les contraintes d'unicité), l'unicité
métier « une fiche par praticien et par clinique », le préfixe `(group_id, clinic_id)` de la requête
de disponibilité, et l'égalité complète de la lecture par compte. Un seul index B-tree, donc, et
aucun autre. Réordonner ces colonnes dégraderait la requête **en silence**.

**Les heures sont des minutes depuis minuit, de 0 à 1440, en horloge murale locale.**
`datetime.time` ne sait pas dire « jusqu'à minuit » : son maximum est `23:59:59.999999`, et
`time.fromisoformat("24:00")` rend `time(0, 0)` **sans lever** — une vacation « 18:00 → minuit »
serait inexprimable, et un document corrigé à la main produirait une plage silencieusement inerte.
1440 dit la fin de journée sans sentinelle cachée, et se laisse contrôler par une simple
`CheckConstraint`. L'intervalle est demi-ouvert `[début, fin)`.

**Les plages sont tenues sous forme canonique : triées, disjointes et MAXIMALES.** Deux plages qui se
**recouvrent** sont refusées — elles disent deux fois autre chose de la même minute, et le dépôt ne
répare jamais en douce une contradiction. Deux plages **jointives**, elles, ne se contredisent pas :
« 09:00-12:00 » suivi de « 12:00-18:00 » désigne exactement les mêmes minutes que « 09:00-18:00 », et
rien dans une plage ne distingue deux tronçons contigus. Elles sont donc **repliées en une seule** à
l'écriture. Ce n'est pas cosmétique : la disponibilité est évaluée par plage — `is_available_for` et
son jumeau SQL demandent qu'**une** plage déclarée contienne le créneau cherché — si bien que sans ce
repli, un praticien présent sans interruption de 09:00 à 18:00 ne répondrait **pas** à une demande de
11:30 à 12:30, et disparaîtrait de la requête du ticket en silence. Une vraie pause de midi reste
deux plages : c'est un **trou**, pas une jonction.

**Le jour de la semaine est `calendar.Day`, convention Python : lundi = 0.** C'est exactement ce que
rend `date.weekday()`, donc aucun vocabulaire inventé. Ce n'est **ni** `EXTRACT(DOW)` (dimanche = 0)
**ni** `EXTRACT(ISODOW)` (lundi = 1) : le nom de la contrainte,
`ck_practitioner_hours_weekday_python_range`, porte la convention jusque dans le schéma PostgreSQL,
et toute requête future qui dériverait un jour depuis une date doit écrire
`EXTRACT(ISODOW FROM d) - 1`.

**Aucun fuseau n'est stocké, et le module le dit.** Convertir « 09:00 » en UTC à l'écriture figerait
le décalage du jour de la saisie : la fiche saisie en janvier ouvrirait à 10:00 locales en juillet,
et aucune migration ne saurait plus distinguer « 08:00 parce qu'on a figé CET » de « 08:00 voulu » —
l'intention serait perdue avec la donnée. Le fuseau est un attribut du **lieu** : il appartient à
`organization`, et la colonne `clinics.timezone` reste à écrire.

**Les deux collections sont des tables enfants relationnelles à clé primaire naturelle.**
`notifications` avait écrit lui-même la condition de sortie du JSONB — « le jour où une requête par
canal existera, elle justifiera sa table », docstring de son modèle de persistance. Ce
jour est celui-ci : la requête du ticket interroge le **contenu** des deux collections, en travers
des lignes, avec un prédicat d'intervalle. Les clés `(profile_id, weekday, start_minute)` et
`(profile_id, species)` **sont** l'index dont les deux `EXISTS` du dépôt ont besoin — zéro index
supplémentaire — et un identifiant de substitution n'aurait servi qu'à inviter le monde extérieur à
référencer une plage horaire.

**Le vocabulaire métier partagé se DUPLIQUE, et une garde le tient.** C'est la règle nouvelle de cet
ADR, et le pendant exact de l'[ADR-0022](./0022-transport-email-partage.md) : un besoin
**technique** partagé par deux modules **descend** dans `shared` ; un **vocabulaire métier** partagé,
lui, se **recopie**. `scheduling` déclare donc son propre catalogue d'espèces, valeur pour valeur, et
`tests/modules/scheduling/test_species_vocabulary.py` — hors du graphe d'import-linter, donc autorisé
à importer les deux côtés — échoue si les deux dérivent. Le précédent était déjà posé par BACK-10a,
qui a recopié les trois types de compte d'`identity` plutôt que d'en faire descendre l'énumération.
Les deux catalogues ne disent d'ailleurs pas la même chose : chez `medical_records` l'espèce est une
**identité** — cet animal _est_ un chien — ici une **compétence** — ce praticien _prend en charge_ les
chiens. La conversion inter-modules est `Species(autre.value)`, et sa place est le point de
composition, seul espace autorisé à connaître deux modules.

**Le port rend une disponibilité DÉCLARÉE, et le dit trois fois.** La fiche n'a aucune fenêtre de
validité : elle survit à l'affectation qui l'a motivée. L'appelant doit croiser le résultat avec les
affectations actives d'`organization`, et ce croisement ne peut pas vivre dans `scheduling` — le
contrat le lui interdit.

## Alternatives écartées

### Laisser horaires et espèces dans `identity`

C'est ce que la page « mon compte » suggère, et c'est un seul formulaire de moins à composer. Écartée :
la table des comptes deviendrait le fourre-tout que le découpage en modules existe pour éviter, et
`scheduling` devrait lire chez `identity` pour apparier un praticien et un animal — exactement la
dépendance que le contrat `module-independence` refuse.

### Une colonne `assignment_id` sur la fiche

La lecture la plus littérale de la carte. Écartée pour deux raisons qui se cumulent : l'ADR-0015
interdit la clé étrangère inter-modules, donc l'identifiant resterait **nu et non résoluble** — le
dépôt ne pourrait ni le valider ni s'en servir pour filtrer ; et une affectation est **datée**, si
bien qu'un renouvellement de contrat rendrait la fiche orpheline sans que rien ne le signale.

### Une clé étrangère composite vers `clinics`, à la manière d'`assignments`

`assignments` rend son invariant physique par `(clinic_id, group_id)` vers `clinics (id, group_id)`.
Écartée ici : ce tour est **intra-module** chez `organization`, alors qu'il traverserait la frontière
depuis `scheduling`. Conséquence assumée et consignée : l'invariant « la clinique appartient au
groupe de la fiche » reste **applicatif**. Le filtre de tenance évite la fuite en lecture, pas
l'incohérence en écriture — la vérification appartient au cas d'usage qui écrira la fiche.

### Des horaires en UTC, en `timestamptz` avec une date pivot, ou en `timetz`

Les trois figent un décalage. L'UTC et la date pivot perdent l'intention avec la donnée, comme dit
plus haut. `timetz` est un type que PostgreSQL déconseille lui-même : sans date, il ne peut pas
résoudre l'heure d'été, si bien qu'il transporte un décalage sans savoir s'il est encore vrai.

### Porter un fuseau sur la fiche technique

Cohérent en apparence : le module stockerait ce dont il a besoin. Écartée pour trois motifs. Le
fuseau est un attribut du **lieu**, pas du praticien — deux praticiens d'une même clinique pourraient
se contredire. **Aucun écrivain** ne le renseignerait dans ce ticket, qui ne livre ni route ni cas
d'usage. Et le jour où `clinics.timezone` existera, deux vérités concurrentes se feraient face.

### Les deux collections en JSONB, à la manière de `channels_by_event`

Le précédent existe, et il est bon — pour la question inverse. La condition de sortie citée plus haut
est celle que `notifications` a écrite dans la docstring de son propre modèle, et consignée à son
[registre d'écarts](../ecarts/back.md#écarts-assumés-avec-le-ticket-back-22) ; elle ne figure pas
dans l'ADR-0021, qui tranche le choix du canal et non la forme du stockage. `notifications` relit ses
préférences **d'un bloc** et n'interroge jamais leur contenu ; ici la requête du ticket interroge le contenu dès
le premier jour, avec un prédicat d'intervalle. En JSONB elle exigerait un `jsonb_array_elements`
latéral non indexable, et la base ne saurait plus contrôler que la fin d'une plage suit son début.

### Faire descendre le catalogue d'espèces dans `shared/domain`

Une seule source de vérité, zéro dérive possible : c'est l'alternative la plus tentante. Écartée
parce que l'ADR-0022 réserve `shared` au besoin **technique** — aucun port de `shared` ne prend une
espèce en argument, à la différence du transport e-mail qui, lui, **type** le sien. Elle obligerait
en outre à modifier `medical_records`, livré, et à déplacer une décision qu'il a prise. Le prix de
l'alternative retenue est nommé : deux énumérations à faire évoluer ensemble, et un test comme seule
garde.

### Passer par les cas d'usage publics du module qui porte le vocabulaire

C'est la voie que prescrit la règle d'indépendance pour les **échanges** entre modules. Elle ne
s'applique pas ici : le contrat interdit à `scheduling` d'atteindre `medical_records` **y compris par
chaîne**, et une énumération consommée dans le domaine — pour typer un champ d'agrégat — ne peut de
toute façon pas transiter par un cas d'usage applicatif.

### Laisser les plages jointives telles qu'elles ont été saisies

C'est ce que la première version livrait, au motif que le domaine « refuse, il ne fusionne pas ».
Écartée à la relecture, qui a montré le faux négatif : le refus vaut pour un **recouvrement**, qui est
une contradiction ; l'adjacence n'en est pas une, et la laisser produisait un praticien silencieusement
absent de la seule requête du ticket. L'alternative de repli — évaluer l'**union** des plages à la
lecture — a été écartée à son tour : elle demanderait à PostgreSQL une agrégation par fenêtre là où un
`EXISTS` suffit, et surtout elle ferait diverger le prédicat SQL de son jumeau en mémoire, qui est
précisément ce que ce module tient d'une seule voix.

### Un franchissement de minuit exprimé par `fin < début`

La garde de nuit, 22:00 → 02:00, en une seule plage. Écartée : elle obligerait **tout** lecteur, pour
toujours, à gérer l'enroulement, et transformerait la clause SQL en disjonction. Une garde de nuit
se saisit en deux plages, `22:00 → 24:00` puis `00:00 → 02:00`. Relâcher la contrainte plus tard est
un `DROP` suivi d'un `ADD CONSTRAINT` qui ne réinterprète aucune ligne existante ; l'autoriser
d'emblée serait irréversible.

## Conséquences

**Ce que le service gagne.** Une fiche technique née au bon endroit, dont le grain — un praticien,
une clinique — supporte le vétérinaire remplaçant sans rien réécrire. Une requête de disponibilité
qui filtre en SQL sur un index qui existe vraiment. Des horaires dont l'intention survivra à
l'arrivée d'un fuseau. Et une règle écrite, mécaniquement gardée, pour le prochain vocabulaire métier
que deux modules voudront partager.

**Ce qu'il paie.** Deux énumérations d'espèces à faire évoluer ensemble, tenues par un test — et ce
test ne tourne pas encore en intégration continue, `pytest` n'étant pas dans le pipeline. L'invariant
« la clinique appartient au groupe de la fiche » reste applicatif, faute de clé étrangère
franchissable. Une garde de nuit se saisit en deux plages. Et `PractitionerProfile` réserve le mot
_profile_ côté praticien : le module `profile` (BACK-32) devra nommer son agrégat autrement —
`IndividualAddress`, `ContactDetails` ou l'équivalent.

**Ce qui reste ouvert.** Le croisement avec les affectations actives est la conséquence la plus
lourde : le port rend une disponibilité **déclarée**, et rien dans ce ticket ne peut rendre le
croisement obligatoire. Si le moteur de rendez-vous l'oublie, un ancien remplaçant reste proposable —
c'est pourquoi le trou est nommé dans la docstring du port, ici, et au registre des écarts. Reste
aussi la colonne `clinics.timezone`, qui appartient à `organization` ; l'écriture de la fiche, avec
son cas d'usage, sa route et son erreur de doublon ; et la doublure en mémoire du module, qui devra
réutiliser le prédicat du domaine plutôt que le réinventer.

**Ce que cet ADR ne déclenche pas.** `medical_records` annonçait, dans son code comme au registre,
que la remontée des utilitaires de fenêtre datée dans `shared/domain` se ferait « au troisième module
daté (BACK-21) ». `scheduling` n'en est pas un : sa fiche ne porte ni début ni fin de validité, aucun
de ses ports ne prend d'instant, et ses seules bornes sont des minutes d'horloge murale — dont la
garde est l'inverse exact de celle des instants. La dette reste due ; son déclencheur passe au moteur
de rendez-vous, et la phrase est corrigée dans le code autant qu'au registre.

## Références

- `backend/api/src/app/modules/scheduling/domain/entities.py` — l'agrégat, l'objet-valeur de plage et
  le catalogue d'espèces recopié.
- `backend/api/src/app/modules/scheduling/domain/policies.py` — les minutes d'horloge murale, et les
  deux raisons de n'y mettre aucun fuseau.
- `backend/api/src/app/modules/scheduling/domain/ports.py` — les deux lectures publiques, et ce que
  « disponible » ne veut pas dire.
- `backend/api/src/app/modules/scheduling/infrastructure/db/models.py` — les trois tables, la
  contrainte unique aux quatre rôles et la convention de jour.
- `backend/api/tests/modules/scheduling/test_species_vocabulary.py` — la garde de non-dérive du
  vocabulaire dupliqué.
