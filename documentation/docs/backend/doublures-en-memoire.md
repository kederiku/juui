---
title: Doublures en mémoire
description: Les fakes du projet — dépôts, unité de travail, cache, stockage, transport et contrôle de fuite — et la suite de conformité qui les empêche de mentir.
---

# Doublures en mémoire

Le guide DDD du projet privilégie explicitement les **Fakes aux Mocks**. BACK-06c livre ce que
cette phrase coûte : des implémentations **complètes** des ports, adossées à des dictionnaires, qui
rendent les tests de cas d'usage rapides et déterministes sans Docker ni base de données.

Une doublure dont le `rollback()` ne fait rien valide une sémantique que la vraie implémentation ne
tient pas. C'est **pire que pas de test** — un test vert affirme quelque chose. Toute cette page
tourne autour de ce risque, et de ce qui l'écarte.

## Où elles vivent

**La doublure suit son port.** C'est la règle, et elle range tout :

| Port                                                                                 | Doublure                                                               | Emplacement                                    |
| ------------------------------------------------------------------------------------ | ---------------------------------------------------------------------- | ---------------------------------------------- |
| `AbstractUnitOfWork`, `Repository`                                                   | `InMemoryUnitOfWork`, `InMemoryRepository`, `InMemoryTenantRepository` | `shared/infrastructure/memory/`                |
| `Cache`                                                                              | `InMemoryCache`                                                        | `shared/infrastructure/memory/`                |
| `FileStorage`                                                                        | `InMemoryFileStorage`                                                  | `shared/infrastructure/memory/`                |
| `EmailTransport`                                                                     | `FakeEmailTransport`                                                   | `shared/infrastructure/memory/`                |
| `BreachChecker`                                                                      | `FakeBreachChecker`                                                    | `shared/infrastructure/memory/`                |
| `AccountRepository`, `IdentityUnitOfWork`, `OtpStore`, `OtpSender`, `OtpDispatcher`  | `InMemory…`, `FakeOtpSender`, `RecordingOtpDispatcher`                 | `modules/identity/infrastructure/memory/`      |
| `NotificationPreferencesRepository`, `NotificationsUnitOfWork`, `NotificationSender` | `InMemory…`, `FakeNotificationSender`                                  | `modules/notifications/infrastructure/memory/` |

Les doublures des ports **métier** ne peuvent pas rejoindre les autres : le contrat
`service-spaces` interdit à `app.shared` d'importer `app.modules`, et un `FakeOtpSender` posé dans
`shared/` ferait échouer `make lint`. La contrainte tombe juste — elle dit la même chose que la
règle.

**Dans `src/`, pas sous `tests/`.** Une classe rangée sous `tests/modules/identity/` n'est
importable que par les tests qui la voisinent, alors que `InMemoryCache` sert à tous les modules et
qu'une sonde de documentation ne peut rien importer de `tests/`. Le raisonnement complet, avec les
alternatives écartées, est dans l'[ADR-0023](../adr/0023-doublures-en-memoire-et-conformite.md).

## Ce qu'un fake doit à son port

**Les écritures sont mises en attente, suppressions comprises.** Le magasin tient trois états : ce
qui est validé, ce que le bloc a écrit, ce que le bloc a supprimé. Le commit replie les deux
derniers dans le premier, le rollback les jette. Une doublure qui ne mettrait que les écritures en
attente laisserait un `delete()` survivre à un rollback.

**Ce qui entre et ce qui sort est une copie**, dans les deux sens, par `deepcopy`. Un dépôt qui
rendrait l'objet rangé laisserait une mutation non validée modifier l'état « persisté » : le test
d'annulation passerait sans rien prouver, puisqu'il comparerait deux références au même objet.

**Le filtrage tenant est reproduit.** `InMemoryTenantRepository` surcharge les **mêmes deux
coutures** que `TenantSqlAlchemyRepository` — `_scope`/`_select` et `_load` — plus l'estampillage.
Sans cela, les tests d'application passeraient sur une isolation que la production applique et pas
eux, et le premier vrai bug d'isolation ne serait jamais attrapé en test rapide.

**Le cache compose ses clés avec le vrai compositeur.** `InMemoryCache` reçoit un `CacheKeyBuilder`
et sérialise avec le `JsonSerializer` de l'adaptateur Redis — les vrais, pas des équivalents. Une
entrée composée sans groupe actif échoue donc exactement là où la production échouerait, un tuple
revient en liste des deux côtés, et une valeur non sérialisable est refusée ici comme là-bas.

**Le temps est injecté.** `FakeClock` fait expirer un code de dix minutes en zéro seconde de test.

## La réponse à la panne, port par port

C'est la moitié du contrat qu'on oublie de vérifier, et les doublures la rendent simulable. Elles
sont **volontairement dissymétriques** — c'est la dissymétrie des ports qu'elles servent :

| Port                 | Devant une panne                                                                 | Dans la doublure                                          |
| -------------------- | -------------------------------------------------------------------------------- | --------------------------------------------------------- |
| `Cache`              | **dégrade** — un cache absent ne change qu'une latence                           | `unavailable=True` → `MISSING`, `False`, `0`              |
| `FileStorage`        | **lève** — un upload silencieux est un fichier perdu                             | `unavailable=True` → `FileStorageUnavailableError`        |
| `EmailTransport`     | **lève** — un message perdu en silence n'est jamais réclamé                      | `fails=True` → `EmailDeliveryError`, et rien n'est retenu |
| `OtpStore`           | **lève**, échec fermé                                                            | `UnavailableOtpStore`                                     |
| `BreachChecker`      | **dégrade** — refuser une inscription parce qu'un tiers est muet coûte plus cher | `unavailable=True` → accepte, et journalise               |
| `AbstractUnitOfWork` | **lève et annule**                                                               | garde de bloc, rollback de sortie                         |

Dans tous les cas, **la validation reste appliquée** : une clé vide, un TTL nul ou une clé qui
traverse son préfixe sont refusés même quand le stockage est simulé injoignable. C'est précisément
quand tout va mal qu'un `../` ne doit pas devenir acceptable.

## La suite de conformité

Rien, dans du code, ne garantit qu'une doublure reste fidèle. Ce qui la fait diverger, c'est le
ticket **suivant**. Seule une suite jouée deux fois le prévient.

`tests/shared/conformance/` porte une classe de base qui contient les tests, et deux sous-classes
qui ne fournissent que la fixture du sujet. La base ne s'appelle pas `Test…`, donc pytest ne la
collecte pas : **un test ajouté à la base est mécaniquement joué des deux côtés**.

| Suite                                        | Côté réel                   | Côté doublure         |
| -------------------------------------------- | --------------------------- | --------------------- |
| Dépôt, unité de travail, tenance, pagination | PostgreSQL, base `app_test` | dictionnaires         |
| Cache                                        | Redis (INFRA-02)            | `InMemoryCache`       |
| Stockage objet                               | MinIO (INFRA-03)            | `InMemoryFileStorage` |

```bash
cd backend/api && uv run pytest -m conformance -v
```

Les moitiés réelles sont **ignorées** quand leur service ne répond pas, avec le message qui dit quoi
lancer. Une suite verte n'est donc pas la preuve que la conformité a été vérifiée : lire les `skip`.

### Ce qu'elle a trouvé le jour de son écriture

Deux divergences, **toutes deux du côté réel** — ce n'est pas la doublure qui mentait :

- `delete()` ne **flushait** pas. `session.delete()` ne fait que marquer la ligne, qui reste dans
  l'identity map : le bloc voyait survivre ce qu'il venait de supprimer, un second `delete`
  réussissait, et un `get` rendait une entité déjà partie.
- `save()` non plus. Une modification se relit sans SQL par l'identity map — ce qui masquait le
  problème — mais une **requête**, elle, part vers la base et `autoflush=False` lui fait lire
  l'état d'avant. Un cas d'usage qui modifiait puis listait dans la même transaction recevait une
  page ordonnée sur ce qu'il venait de remplacer : des éléments justes, dans un ordre faux, et rien
  pour le signaler.

Les trois écritures du dépôt générique flushent désormais, comme `add` le faisait déjà.

### Ce qu'elle ne couvre pas, et pourquoi

**Les contraintes du stockage** — unicité, clé étrangère, `NOT NULL`, ordre des `NULL` dans un tri.
Les inventer dans la doublure serait mentir dans l'autre sens : un test échouerait pour une règle
que la vraie base n'applique peut-être pas ainsi. Elles sont l'objet des tests d'**infrastructure**
sur vraie base, troisième niveau de la stratégie de BACK-12. Seule la collision d'identifiant est
reproduite, parce que l'alternative serait un écrasement silencieux, ce qu'aucune base ne fait.

**La réponse à la panne**, qui se simule d'un côté et demanderait d'arrêter un conteneur de
l'autre. Elle est éprouvée sur la seule doublure, dans `tests/shared/memory/`.

## Écrire la doublure d'un module

Le socle rend l'exercice mécanique. Un dépôt déclare son erreur d'absence, son message — **mot pour
mot celui du dépôt réel**, sans quoi la conformité comparerait deux vocabulaires — et ses champs
triables :

```python
class InMemoryAccountRepository(InMemoryRepository[Account], AccountRepository):
    _not_found_error = AccountNotFoundError
    _not_found_message = "Aucun compte ne porte l'identifiant {entity_id}."
```

Une unité de travail déclare ses magasins et expose ses dépôts en **propriétés** gardées :

```python
class InMemoryIdentityUnitOfWork(InMemoryUnitOfWork, IdentityUnitOfWork):
    def __init__(self, accounts: Iterable[Account] = ()) -> None:
        super().__init__()
        self._accounts: InMemoryStore[Account] = self._new_store()
        for account in accounts:
            self._accounts.seed(account)

    @property
    def accounts(self) -> AccountRepository:
        self._require_open()
        return InMemoryAccountRepository(self._accounts)
```

`_new_store()` inscrit le magasin au **commit atomique** : un magasin construit sans passer par lui
ne serait ni commité ni annulé avec les autres. `accounts_store.committed_entity(id)` relit l'état
validé hors de tout bloc — ce qu'un test interroge pour prouver qu'un commit a bien eu lieu.

`organization` et `medical_records` n'ont pas encore les leurs : aucun cas d'usage ne les consomme,
et leurs _finders_ maison seraient réimplémentés pour personne.

## La règle à tenir

**Une doublure qui gagne un comportement gagne sa ligne de conformité dans le même commit.** C'est
la seule discipline que ce dispositif demande, et la seule qui le maintienne utile.
