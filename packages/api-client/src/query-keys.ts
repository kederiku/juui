/**
 * FRONT-04 -- La fabrique de clefs de cache : ou une reponse se range, et ce
 * qui la rend incomparable a celle d'un autre groupe.
 *
 * POURQUOI CE FICHIER EXISTE
 * Orval exporte deja une clef par operation -- `getCheckReadinessQueryKey()`
 * rend `['/health/ready']`. Elle identifie une ROUTE, et rien d'autre. Or la
 * meme route rend des donnees differentes selon le groupe actif du jeton
 * (ADR-0004, ADR-0012). S'en tenir a la clef d'Orval ferait qu'un veterinaire
 * remplacant qui bascule de structure continue de lire les donnees de la
 * precedente pendant tout le staleTime. Sur des donnees medicales entre deux
 * groupes distincts, ce n'est pas un defaut d'affichage.
 *
 * CE FICHIER N'A AUCUN IMPORT, ET C'EST PORTEUR -- A LIRE AVANT D'EN AJOUTER UN
 * Node 24 efface les types a la volee : il execute donc ce fichier TEL QUEL,
 * sans compilation. C'est ce qui permet a `scripts/verify-query-keys.ts` de
 * prouver la bascule hors ligne -- sans pile demarree, sans dependance et sans
 * runner de test, que le depot n'aura pas avant QA-02. Un import de TYPE
 * survivrait a l'effacement ; un import de VALEUR ferait tomber la propriete,
 * Node restant un resolveur ESM et les imports relatifs du depot s'ecrivant
 * sans extension -- mesure, `node src/mutator.ts` sort en ERR_MODULE_NOT_FOUND
 * sur exactement cette ligne. Ce qui a besoin d'une valeur va dans
 * query-client.ts.
 *
 * PAR-DESSUS ORVAL, ET JAMAIS A SA PLACE
 * La clef generee est reprise TELLE QUELLE, en queue -- y compris les
 * parametres de requete, qu'Orval range deja dans la sienne. Recopier
 * `['/health/ready']` a la main rendrait l'invalidation muette le jour ou le
 * backend renomme un chemin -- c'est la raison pour laquelle SHARED-03 a active
 * `shouldExportQueryKey`, en renvoyant nommement a ce ticket.
 *
 * L'ORDRE DES SEGMENTS EST LE CONTRAT (ADR-0027)
 * Portee, valeurs de portee, puis la clef d'Orval INTACTE et EN DERNIER.
 * TanStack Query n'apparie que par PREFIXE : du plus general au plus precis est
 * la seule disposition ou `tenantScopeKey(scope)` veuille dire « tout ce
 * groupe, et lui seul ». Contrepartie assumee, et voulue : on ne peut pas
 * invalider « cette route, tous groupes confondus ».
 *
 * CE QUE LE TYPAGE TIENT, ET CE QU'IL NE TIENT PAS
 * Il tient qu'une clef composee PAR CES FABRIQUES porte un groupe, et que la
 * chaine mise en position de groupe a ete marquee comme telle. Il ne tient pas
 * ce qui ne passe pas par elles : un hook genere appele nu se range encore sous
 * la clef d'Orval, et une clef de portee peut etre renfermee dans une autre
 * (`publicQueryKey(groupQueryKey(...))` compile), ce qui la rendrait invisible
 * a la purge. Ces deux limites sont consignees au registre des ecarts ; la
 * parade mecanique et sa condition de reouverture sont dans l'ADR-0027.
 *
 * CE QUE CE FICHIER NE FAIT PAS
 * Il ne dit pas QUEL est le groupe actif : personne ne le sait avant FRONT-07
 * (`useAuth`). Aucun contexte React ici a dessein -- un contexte livre par ce
 * ticket rendrait `null` faute de source, c'est-a-dire une clef tenant sans
 * groupe : precisement ce que le critere interdit. Et il ne purge rien : la
 * purge totale a la bascule appartient a FRONT-08, a qui ce fichier ne fournit
 * que le prefixe qui la rend exacte.
 */

/**
 * Identifiant du groupe actif, tel que le claim `active_group_id` du jeton le
 * porte (ADR-0012).
 *
 * MARQUE, ET NON UN `string` NU. Sans la marque, un identifiant de clinique, de
 * compte ou de requete entrerait dans la case du groupe sans que rien ne le
 * signale -- et la clef obtenue serait valide, stable, et fausse.
 */
export type GroupId = string & { readonly __brand: 'GroupId' };

/** Identifiant de la clinique active, celle de l'en-tete `X-Clinic-Id` (ADR-0012). */
export type ClinicId = string & { readonly __brand: 'ClinicId' };

/**
 * Une chaine qui n'a PAS deja ete marquee.
 *
 * C'est le type des deux fabriques ci-dessous, et il ferme un trou reel : sans
 * lui, `asGroupId(clinicId)` compilerait -- un `ClinicId` etant assignable a
 * `string` -- et remarquerait une clinique en groupe. La propriete optionnelle
 * `__brand?: undefined` est satisfaite par toute chaine nue et par elle seule.
 */
type Unbranded = string & { readonly __brand?: undefined };

/** La portee d'une requete de groupe : au minimum, le groupe. */
export type GroupScope = { readonly groupId: GroupId };

/**
 * La portee d'une requete de clinique. Elle ETEND `GroupScope` -- une clinique
 * appartient toujours a un groupe.
 *
 * Une VARIABLE de ce type se passe indifferemment aux deux fabriques. Un
 * litteral, non : le controle des proprietes excedentaires refuse
 * `groupQueryKey({ groupId, clinicId }, ...)`. C'est voulu -- le site d'appel
 * declare la portee qu'il consomme.
 */
export type ClinicScope = GroupScope & { readonly clinicId: ClinicId };

/**
 * Le premier segment des clefs qui portent des donnees de groupe.
 *
 * UN MARQUEUR, ET NON RIEN. Sans lui, purger un groupe reviendrait a purger
 * « tout ce qui commence par cet identifiant » : la frontiere de tenance ne se
 * lirait plus dans la clef, ni dans les Devtools.
 */
const TENANT_SEGMENT = 'tenant';

/** Le segment qui ouvre le niveau clinique, SOUS celui du groupe. */
const CLINIC_SEGMENT = 'clinic';

/**
 * Marque une chaine comme identifiant de groupe.
 *
 * LEVE PLUTOT QUE DE SE REPLIER, meme regle que `resolveBaseUrl` : une chaine
 * vide ou blanche produirait `['tenant', '', ...]`, un seau que TOUS les
 * utilisateurs sans groupe partageraient. C'est la fuite exacte que ce fichier
 * existe pour rendre impossible, et elle ne se signalerait par aucune erreur.
 *
 * La garde ne voit RIEN d'une valeur qui n'est jamais passee par ici -- un
 * `{ groupId: claims.active_group_id }` construit depuis un decodage type `any`
 * lui echappe. C'est la limite du typage structurel, elle est nommee en tete de
 * fichier, et c'est FRONT-07 qui devra faire de cette fabrique son unique
 * porte d'entree depuis le jeton.
 */
export function asGroupId(value: Unbranded): GroupId {
  if (value.trim() === '') {
    throw new Error(
      'FRONT-04 : un identifiant de groupe vide ne peut pas entrer dans une clef de cache.',
    );
  }
  // Deux assertions : `Unbranded` porte `__brand?: undefined`, incompatible en
  // une passe avec `__brand: 'GroupId'`. Le detour par `string` est ce qui
  // permet a la marque de refuser une chaine DEJA marquee a l'entree.
  return value as string as GroupId;
}

/** Marque une chaine comme identifiant de clinique. Meme garde qu'`asGroupId`. */
export function asClinicId(value: Unbranded): ClinicId {
  if (value.trim() === '') {
    throw new Error(
      'FRONT-04 : un identifiant de clinique vide ne peut pas entrer dans une clef de cache.',
    );
  }
  return value as string as ClinicId;
}

/**
 * Clef d'une ressource PUBLIQUE -- lisible sans jeton, identique pour tous : les
 * sondes de sante, la vitrine de `frontend-individual`.
 *
 * Aucun groupe, parce qu'il n'y en a pas. Le segment de tete existe pour que ce
 * soit VISIBLE dans les Devtools, plutot que deduit d'une absence.
 */
export function publicQueryKey<TKey extends readonly unknown[]>(
  operationKey: TKey,
): readonly ['public', ...TKey] {
  return ['public', ...operationKey];
}

/**
 * Le prefixe de TOUTES les clefs d'un groupe -- celles du groupe comme celles de
 * ses cliniques.
 *
 * C'est la cible unique de la purge de FRONT-08 et de toute invalidation « tout
 * ce groupe ». Il prend le groupe QUITTE, qu'il faut donc capturer AVANT la
 * reemission du jeton, et la purge s'annonce par une annulation :
 *
 *   await queryClient.cancelQueries({ queryKey: tenantScopeKey(precedent) });
 *   queryClient.removeQueries({ queryKey: tenantScopeKey(precedent) });
 */
export function tenantScopeKey(scope: GroupScope): readonly ['tenant', GroupId] {
  return [TENANT_SEGMENT, scope.groupId];
}

/**
 * Clef d'une ressource DU GROUPE : la liste de ses cliniques, ses comptes, ses
 * roles. Une bascule de groupe change la clef, donc l'entree de cache -- c'est
 * la ligne qui tient le critere du ticket.
 */
export function groupQueryKey<TKey extends readonly unknown[]>(
  scope: GroupScope,
  operationKey: TKey,
): readonly ['tenant', GroupId, ...TKey] {
  return [TENANT_SEGMENT, scope.groupId, ...operationKey];
}

/**
 * Clef d'une ressource D'UNE CLINIQUE.
 *
 * LA CLINIQUE ENTRE DANS LA CLEF BIEN QU'ELLE NE SOIT PAS DANS LE JETON.
 * L'ADR-0012 la fait basculer cote client, sans reemission : changer de
 * clinique DANS UN MEME ONGLET ne change ni la route ni la clef d'Orval, et le
 * mutator envoie `X-Clinic-Id` par requete. Une clef commune donnerait donc UNE
 * entree aux deux, et la seconde afficherait les donnees de la premiere pendant
 * tout le staleTime -- la panne du ticket, un cran plus bas, a l'interieur d'un
 * perimetre pourtant autorise. (Deux ONGLETS, eux, ont deux QueryClient et ne
 * partagent rien : le cache vit en memoire, le depot n'installe aucun
 * persister.)
 *
 * RESERVEE AUX RESSOURCES DE NIVEAU CLINIQUE. Mettre la clinique dans TOUTES
 * les clefs tenant dupliquerait le cache d'une donnee qui n'en depend pas -- la
 * liste des cliniques d'un groupe -- et l'invalidation manquerait les entrees
 * soeurs. C'est la RESSOURCE qui decide, pas le site d'appel.
 *
 * SOUS le segment du groupe et non a cote : `tenantScopeKey` doit couvrir les
 * deux familles d'un seul prefixe.
 */
export function clinicQueryKey<TKey extends readonly unknown[]>(
  scope: ClinicScope,
  operationKey: TKey,
): readonly ['tenant', GroupId, 'clinic', ClinicId, ...TKey] {
  return [TENANT_SEGMENT, scope.groupId, CLINIC_SEGMENT, scope.clinicId, ...operationKey];
}
