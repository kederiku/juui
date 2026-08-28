/**
 * FRONT-10 -- La traduction des codes d'erreur en phrases lisibles.
 *
 * LE SERVEUR CHOISIT LE CODE, LE CLIENT CHOISIT LE MESSAGE. BACK-09 rend un
 * `message` avec chaque erreur, mais il est ecrit POUR UN DEVELOPPEUR -- « La
 * requete ne respecte pas le schema attendu. » -- et il n'est traduit nulle
 * part. L'afficher ferait parler a l'interface un dialecte interne, et lierait
 * le texte vu par un veterinaire a une chaine de caractere du serveur que
 * personne ne relit. `ApiError.message` reste donc un message de JOURNAL ;
 * seule cette table sort a l'ecran.
 *
 * AUCUN IMPORT DE VALEUR DANS CE FICHIER, ET C'EST PORTEUR. Le depot n'a aucun
 * runner de test frontend (QA-02), et la seule preuve mecanique disponible est
 * `node scripts/verify-errors.ts`. Or Node reste un resolveur ESM : il exige
 * une extension explicite, que les imports relatifs du depot n'ecrivent jamais
 * -- mesure, `ERR_MODULE_NOT_FOUND`. Passer par l'auto-reference du package
 * (`@repo/api-client/errors/messages`) resout le fichier D'ENTREE, mais
 * `tsconfig.verify.json` compile ce dossier en `moduleResolution: node10`, qui
 * ignore les cartes `exports` : un import interne par ce chemin casserait
 * `make verify-api-client`. Table et resolution vivent donc ENSEMBLE, sans
 * aucun import de valeur. Les `import type` sont effaces, donc gratuits.
 *
 * LES MESSAGES SONT ACCENTUES, LES COMMENTAIRES NE LE SONT PAS. C'est la regle
 * du depot : les accents s'arretent au Markdown, sauf pour ce qui s'affiche --
 * « cliniques veterinaires » a l'ecran d'un cabinet serait une faute.
 */

import type { ApiError } from './api-error';

/*
 * LES PHRASES QUI SERVENT DEUX FOIS SONT NOMMEES. Une meme formulation apparait
 * a la fois sur un code precis et sur le repli de son statut -- « introuvable »
 * en est l'exemple qui compte. Les recopier laisserait l'une des deux deriver a
 * la premiere reformulation, et la sonde de vocabulaire ne verifie que le
 * VOCABULAIRE, pas l'egalite. Une constante dit que l'egalite est VOULUE.
 */
const NOT_FOUND = 'Cet élément est introuvable.';
const FORBIDDEN = 'Vous n’avez pas accès à cette action.';
const CONFLICT = 'Cette action est incompatible avec l’état actuel de l’élément.';
const TOO_MANY = 'Trop de tentatives. Patientez quelques instants, puis réessayez.';
const SESSION_EXPIRED = 'Votre session a expiré. Reconnectez-vous pour continuer.';
const SESSION_INVALID = 'Votre session est invalide. Reconnectez-vous pour continuer.';
const WRONG_APPLICATION = 'Cette session n’est pas valable sur cette application.';
const INVALID_INPUT = 'Certaines informations saisies ne sont pas valides.';
const UNREACHABLE = 'Le service n’a pas répondu. Vérifiez votre connexion, puis réessayez.';
const UNAVAILABLE = 'Le service est momentanément indisponible. Réessayez dans quelques instants.';
const INTERNAL_ERROR = 'Le service a rencontré une erreur interne. L’incident a été enregistré.';

/**
 * Ce que l'ecran a besoin de savoir d'une erreur.
 *
 * DEUX CHAMPS POUR L'IDENTIFIANT, ET C'EST VOULU. `requestId` est ce qui est
 * ARRIVE ; `visibleRequestId` est ce qu'il faut AFFICHER, et il vaut `null` des
 * qu'il n'y a rien a montrer. Un drapeau booleen aurait oblige chaque appelant a
 * recouper « faut-il l'afficher » avec « y en a-t-il un », et le premier qui
 * l'aurait oublie affichait un bloc vide. Le cas est loin d'etre theorique : un
 * vrai 500 ne traverse aucun intergiciel CORS (ecart BACK-11), le navigateur le
 * presente au JavaScript comme un echec reseau, et l'identifiant est perdu.
 */
export type ResolvedError = {
  /** La phrase a afficher. Jamais vide, quelle que soit l'entree. */
  message: string;
  /** Le code d'origine -- pour la journalisation et les rapports, pas pour l'ecran. */
  code: string;
  /** Le statut HTTP, ou 0 quand aucune reponse n'est parvenue. */
  status: number;
  requestId: string | null;
  /**
   * Vrai quand aucune entree de la table ne portait ce code.
   *
   * Vrai AUSSI pour la famille derivee `http.request.<statut>`, que le repli
   * par statut couvre a dessein : c'est un fait sur la table, pas un reproche.
   * Seuls les codes METIER non traduits sont journalises.
   */
  isUnknownCode: boolean;
  /** L'identifiant a afficher, ou `null` s'il n'y a rien a montrer d'utile. */
  visibleRequestId: string | null;
};

/** Codes fabriques par le client lui-meme (voir `api-error.ts`). */
const CLIENT_MESSAGES = {
  'api_client.transport.unreachable': UNREACHABLE,
  // NE PARLE PAS DU FORMAT, ET C'EST UNE CORRECTION DE REVUE. Ce code se leve
  // aussi sur une reponse parfaitement conforme au contrat mais qui n'est pas
  // une erreur BACK-09 -- le 503 de `/health/ready`, dont le corps est un
  // `ReadinessReport`. Dire « reponse inattendue » serait faux dans ce cas, qui
  // est le plus frequent des trois (les deux autres etant une passerelle en
  // panne et un preflight refuse). Le detail technique reste dans
  // `ApiError.message` et dans `rawBody`, pour qui lit les journaux.
  'api_client.response.malformed': UNAVAILABLE,
  // Pose par ce fichier quand la configuration du deploiement est fausse. Le
  // texte ne propose PAS de reessayer : rien ne changerait (voir plus bas).
  'api_client.configuration.invalid':
    'L’application n’est pas correctement configurée. Signalez-le à votre administrateur.',
  /** Ce qui a ete attrape n'est pas une erreur d'API reconnaissable. */
  'api_client.error.unrecognized': 'Une erreur est survenue. Réessayez dans quelques instants.',
} as const;

/** Erreurs de protocole, posees par les handlers de BACK-09 eux-memes. */
const HTTP_MESSAGES = {
  'http.request.validation_error': INVALID_INPUT,
  'http.server.internal_error': INTERNAL_ERROR,
} as const;

/**
 * Les categories partagees et les objets-valeurs de `shared`.
 *
 * LES DIX CODES `shared.token.*` SORTENT EN 400 AUJOURD'HUI et en 401 quand
 * BACK-10c aura pose la bordure d'authentification : `TokenError` n'a pas
 * encore de categorie intermediaire. Les phrases sont donc ecrites pour tenir
 * dans les deux mondes -- elles parlent de la SESSION, jamais du statut.
 */
const SHARED_MESSAGES = {
  'shared.domain.error': 'Cette action n’a pas pu aboutir.',
  'shared.resource.not_found': NOT_FOUND,
  'shared.resource.already_exists': 'Un élément identique existe déjà.',
  'shared.resource.conflict': CONFLICT,
  'shared.resource.invalid': 'Cette valeur n’est pas acceptée.',
  'shared.resource.forbidden': FORBIDDEN,
  'shared.request.too_many': TOO_MANY,

  'shared.pagination.invalid': 'Cette page ne peut pas être affichée.',
  'shared.pagination.unknown_sort': 'Ce critère de tri est inconnu.',

  'shared.password.invalid': 'Ce mot de passe ne respecte pas la politique de sécurité.',
  'shared.password.too_short': 'Ce mot de passe est trop court : 14 caractères au minimum.',
  'shared.password.too_long': 'Ce mot de passe est trop long : 128 caractères au maximum.',
  // Le message DIT ce qui s'est passe : un mot de passe correct par sa forme
  // mais connu des fuites publiques. Sans cette phrase, l'utilisateur croit a
  // un bug -- il vient de saisir un mot de passe qui respecte les regles.
  'shared.password.breached':
    'Ce mot de passe apparaît dans des fuites de données publiques. Choisissez-en un autre.',

  'shared.file.error': 'Ce fichier n’a pas pu être traité.',
  'shared.file.not_found': 'Ce fichier est introuvable.',
  'shared.file.too_large': 'Ce fichier est trop volumineux.',
  'shared.file.unsupported_content_type': 'Ce format de fichier n’est pas accepté.',
  'shared.file.invalid_key': 'Cette référence de fichier est invalide.',
  // N'ATTEINT JAMAIS LE NAVIGATEUR aujourd'hui : le handler de BACK-09 la
  // re-leve vers le 500 generique, panne technique et non refus metier. Ecrite
  // quand meme -- elle ne coute rien et sera juste le jour ou elle sortira.
  'shared.file.storage_unavailable':
    'Le stockage des fichiers est momentanément indisponible. Réessayez plus tard.',

  'shared.token.invalid': SESSION_INVALID,
  'shared.token.expired': SESSION_EXPIRED,
  'shared.token.not_yet_valid': 'Votre session n’est pas encore utilisable. Reconnectez-vous.',
  'shared.token.invalid_signature': SESSION_INVALID,
  'shared.token.malformed': SESSION_INVALID,
  'shared.token.wrong_type': SESSION_INVALID,
  // AUDIENCE : le jeton est valide, mais pour une AUTRE application. Le dire
  // ainsi evite la boucle « je me reconnecte et ca recommence ».
  'shared.token.invalid_audience': WRONG_APPLICATION,
  'shared.token.unknown_audience': WRONG_APPLICATION,
  'shared.token.unknown_account_type': 'Ce type de compte n’est pas reconnu.',
  'shared.token.membership_not_active':
    'Votre accès à cette structure n’est plus actif. Reconnectez-vous pour continuer.',
} as const;

/**
 * Le module `identity` : comptes, verification d'adresse.
 *
 * NON-DIVULGATION -- `identity.account.email_already_used` porte un refus
 * NEUTRE. Le backend evite deja de dire qu'une adresse est prise (BACK-09,
 * BACK-28) ; ecrire ici « cet e-mail existe deja » retablirait exactement la
 * fuite qu'il evite, au nom du confort d'usage. Le code, lui, reste lisible
 * dans `ApiError.code` : c'est une donnee de diagnostic, pas un texte affiche.
 */
const IDENTITY_MESSAGES = {
  'identity.account.not_found': 'Ce compte est introuvable.',
  'identity.account.email_already_used':
    'Cette inscription n’a pas pu aboutir. Vérifiez vos informations, puis réessayez.',
  'identity.account.email_already_verified': 'Cette adresse est déjà vérifiée.',
  'identity.account.invalid_status_transition':
    'Ce changement d’état n’est pas possible pour ce compte.',
  'identity.otp.invalid_code': 'Ce code est incorrect ou a expiré.',
  'identity.otp.attempts_exhausted':
    'Trop de tentatives : ce code est désormais invalide. Demandez-en un nouveau.',
  'identity.otp.resend_throttled':
    'Un code vient déjà de vous être envoyé. Patientez avant d’en demander un autre.',
} as const;

/**
 * Le module `organization` : groupes, cliniques, appartenances.
 *
 * TOUT CE QUI EST INTROUVABLE SE DIT « INTROUVABLE ». Le backend repond 404 --
 * et non 403 -- pour une ressource appartenant a un autre groupe (ADR-0014,
 * qui porte la regle ; ADR-0013 en donne le mecanisme cote depot) :
 * un refus de droit confirmerait son existence chez un concurrent. Formuler
 * ici « vous n'avez pas les droits » annulerait la precaution prise cote
 * serveur, et c'est la raison d'etre de la sonde de vocabulaire.
 */
const ORGANIZATION_MESSAGES = {
  'organization.membership.not_found': 'Cette appartenance est introuvable.',
  'organization.assignment.not_found': 'Cette affectation est introuvable.',
  'organization.window.invalid': 'Ces dates ne forment pas une période valide.',
  'organization.assignment.outside_active_membership':
    'Cette affectation sort de la période d’appartenance au groupe.',
} as const;

/** Le module `scheduling` : fiches praticien, plages horaires. */
const SCHEDULING_MESSAGES = {
  'scheduling.practitioner_profile.not_found': 'Cette fiche praticien est introuvable.',
  'scheduling.time_range.invalid': 'Cette plage horaire n’est pas valide.',
  'scheduling.time_ranges.overlapping': 'Ces plages horaires se chevauchent.',
  'scheduling.species.unknown': 'Cette espèce n’est pas reconnue.',
} as const;

/** Le module `notifications` : preferences et envois. */
const NOTIFICATIONS_MESSAGES = {
  'notifications.preferences.not_found': 'Ces préférences de notification sont introuvables.',
  'notifications.preferences.event_not_configurable':
    'Cette notification est indispensable au service : elle ne peut pas être désactivée.',
  'notifications.preferences.unknown_event': 'Ce type de notification n’est pas reconnu.',
  'notifications.preferences.unknown_channel': 'Ce canal de notification n’est pas reconnu.',
  'notifications.delivery.missing_payload': 'Cette notification n’a pas pu être envoyée.',
} as const;

/** Le module `medical_records` : animaux et detentions. */
const MEDICAL_RECORDS_MESSAGES = {
  'medical_records.animal.not_found': 'Cet animal est introuvable.',
  'medical_records.custody.not_found': 'Cette détention est introuvable.',
  'medical_records.window.invalid': 'Ces dates ne forment pas une période valide.',
  'medical_records.custody.already_active': 'Cet animal a déjà un détenteur actif.',
} as const;

/**
 * La table complete, code -> message.
 *
 * FUSION D'ENREGISTREMENTS NOMMES plutot qu'un seul objet a sections : le
 * decoupage par module est celui du backend, il se lit dans le type, et une
 * sonde verifie qu'aucune clef n'est ecrasee silencieusement d'un
 * enregistrement a l'autre.
 */
export const ERROR_MESSAGES: Readonly<Record<string, string>> = {
  ...CLIENT_MESSAGES,
  ...HTTP_MESSAGES,
  ...SHARED_MESSAGES,
  ...IDENTITY_MESSAGES,
  ...ORGANIZATION_MESSAGES,
  ...SCHEDULING_MESSAGES,
  ...NOTIFICATIONS_MESSAGES,
  ...MEDICAL_RECORDS_MESSAGES,
};

/** Les huit enregistrements, exposes pour la sonde de collision. */
export const MESSAGES_BY_MODULE: ReadonlyArray<Readonly<Record<string, string>>> = [
  CLIENT_MESSAGES,
  HTTP_MESSAGES,
  SHARED_MESSAGES,
  IDENTITY_MESSAGES,
  ORGANIZATION_MESSAGES,
  SCHEDULING_MESSAGES,
  NOTIFICATIONS_MESSAGES,
  MEDICAL_RECORDS_MESSAGES,
];

/**
 * Repli par statut, quand le code n'est pas dans la table.
 *
 * CE N'EST PAS UN FILET DE SECOURS FACULTATIF. Les erreurs de routage portent
 * un code DERIVE du statut (`http.request.not_found`,
 * `http.request.method_not_allowed`, et un par entree du registre HTTP) :
 * les enumerer serait recopier la bibliotheque standard de Python. C'est donc
 * ce repli qui les couvre -- et c'est lui qui tient la regle de vocabulaire
 * meme sur un code que personne n'a catalogue.
 */
export const STATUS_MESSAGES: Readonly<Record<number, string>> = {
  0: UNREACHABLE,
  400: 'Cette demande n’a pas pu être traitée.',
  401: SESSION_EXPIRED,
  403: FORBIDDEN,
  // « INTROUVABLE », JAMAIS « VOUS N'AVEZ PAS LES DROITS ». Voir
  // ORGANIZATION_MESSAGES : c'est la meme regle, et elle vaut d'autant plus ici
  // que ce message couvre les codes inconnus.
  404: NOT_FOUND,
  409: CONFLICT,
  422: INVALID_INPUT,
  429: TOO_MANY,
  // LES 5xx SONT NOMMES, et pas laisses au message generique : un refus qui
  // vient du service ne se corrige pas en changeant sa saisie, et le dire evite
  // que l'utilisateur cherche ce qu'il a mal fait.
  500: INTERNAL_ERROR,
  502: UNAVAILABLE,
  503: UNAVAILABLE,
  504: 'Le service a mis trop de temps à répondre. Réessayez dans quelques instants.',
};

/**
 * Le prefixe des codes DERIVES du statut par les handlers de BACK-09.
 *
 * MESURE A L'ECRAN, ET C'EST POURQUOI CETTE CONSTANTE EXISTE. Un 404 de
 * routage sort en `http.request.not_found`, un 405 en
 * `http.request.method_not_allowed`, et il y en a un par entree du registre
 * HTTP -- aucun n'est dans la table, par choix : les enumerer serait recopier
 * la bibliotheque standard de Python, et le repli par statut dit exactement la
 * meme chose. Sans cette exception, chaque 404 ordinaire ecrirait donc un
 * avertissement « code inconnu » dans la console, et l'avertissement qui
 * compte -- un code METIER oublie -- se noierait dedans.
 */
const DERIVED_CODE_PREFIX = 'http.request.';

/** Le dernier repli : ni code connu, ni statut connu. Jamais un ecran vide. */
export const GENERIC_MESSAGE = 'Une erreur est survenue. Réessayez dans quelques instants.';

/**
 * Messages de champ, indexes par le `type` de violation Pydantic.
 *
 * ON NE MONTRE JAMAIS `details.errors[].msg` : il est en ANGLAIS et vient du
 * serveur (« Field required », « Extra inputs are not permitted »). La regle
 * « jamais le message brut du backend » vaut aussi au niveau du champ, et
 * `type` est justement le discriminant machine prevu pour cela.
 */
export const VALIDATION_TYPE_MESSAGES: Readonly<Record<string, string>> = {
  missing: 'Ce champ est obligatoire.',
  extra_forbidden: 'Ce champ n’est pas attendu.',
  string_too_short: 'Cette valeur est trop courte.',
  string_too_long: 'Cette valeur est trop longue.',
  string_pattern_mismatch: 'Ce format n’est pas valide.',
  string_type: 'Cette valeur doit être du texte.',
  int_parsing: 'Cette valeur doit être un nombre entier.',
  int_type: 'Cette valeur doit être un nombre entier.',
  float_parsing: 'Cette valeur doit être un nombre.',
  bool_parsing: 'Cette valeur doit être « oui » ou « non ».',
  date_parsing: 'Cette date n’est pas valide.',
  date_from_datetime_parsing: 'Cette date n’est pas valide.',
  datetime_parsing: 'Cette date n’est pas valide.',
  uuid_parsing: 'Cet identifiant n’est pas valide.',
  greater_than: 'Cette valeur est trop petite.',
  greater_than_equal: 'Cette valeur est trop petite.',
  less_than: 'Cette valeur est trop grande.',
  less_than_equal: 'Cette valeur est trop grande.',
  enum: 'Cette valeur ne fait pas partie des choix possibles.',
  literal_error: 'Cette valeur ne fait pas partie des choix possibles.',
  value_error: 'Cette valeur n’est pas acceptée.',
};

/** Repli de champ, pour un `type` de violation que Pydantic vient d'inventer. */
export const GENERIC_FIELD_MESSAGE = 'Cette valeur n’est pas acceptée.';

/**
 * Lit une table de messages SANS jamais tomber sur `Object.prototype`.
 *
 * MESURE, ET C'EST UN DEFAUT QUE LA REVUE A REPRODUIT. `ERROR_MESSAGES` est un
 * objet litteral ordinaire : `ERROR_MESSAGES['constructor']` rendait la
 * FONCTION heritee, `['__proto__']` un objet. Le champ `message`, type `string`
 * et promis « jamais vide », valait alors une fonction -- ecran vide -- ou un
 * objet -- l'arbre React tombait sur « Objects are not valid as a React child ».
 * Et `isUnknownCode` restait faux, donc rien n'etait journalise.
 *
 * Le code vient du CORPS de la reponse : `normalizeErrorResponse` le recopie des
 * qu'il est une chaine. Le backend Juui n'emettra jamais ces codes, mais la
 * promesse ecrite est « quelle que soit l'entree », et une promesse absolue se
 * tient absolument.
 */
function lookup(table: Readonly<Record<string, string>>, key: string): string | undefined {
  return Object.hasOwn(table, key) ? table[key] : undefined;
}

/**
 * La forme d'une `ApiError`, reconnue STRUCTURELLEMENT.
 *
 * Pourquoi pas `isApiError` : ce serait un import de VALEUR, et le fichier
 * cesserait d'etre executable par Node -- voir l'en-tete. La garde reste sure :
 * `ApiConfigurationError` est traitee AVANT, et rien d'autre dans le depot ne
 * porte cette combinaison de champs.
 */
type ApiErrorShape = Pick<ApiError, 'status' | 'code' | 'details' | 'requestId'>;

function isApiErrorShape(value: unknown): value is ApiErrorShape {
  if (typeof value !== 'object' || value === null) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return typeof candidate.status === 'number' && typeof candidate.code === 'string';
}

/**
 * Les codes deja signales, pour ne les journaliser qu'une fois.
 *
 * `resolveApiError` est appelee DANS LE CORPS DU RENDU -- c'est la forme que la
 * documentation montre et que le consommateur emploie. Sans ce garde-fou, un
 * code non traduit ecrit une ligne a chaque rendu, doublee sous `StrictMode`, et
 * l'avertissement qui compte se noie dans ses propres repetitions.
 */
const reportedCodes = new Set<string>();

/** Reconnait la panne de configuration sans importer sa classe. */
function isConfigurationError(value: unknown): boolean {
  return value instanceof Error && value.name === 'ApiConfigurationError';
}

/**
 * Traduit une erreur en ce que l'ecran doit en montrer.
 *
 * TROIS BRANCHES, ET LA DEUXIEME EST UNE DETTE EVITEE. `ApiConfigurationError`
 * n'est PAS une `ApiError`, exprès : « l'API n'a rien refuse, c'est le
 * deploiement qui est faux » (SHARED-03). La faire tomber dans le repli
 * generique afficherait « reessayez dans quelques instants » devant une base
 * URL absente -- et personne ne reessaierait avec succes. Son message
 * d'origine, lui, dit quoi faire : il part au journal.
 *
 * @param error Ce qu'un `catch` ou TanStack Query a rendu -- n'importe quoi.
 * @returns De quoi remplir l'ecran, avec un message jamais vide.
 */
export function resolveApiError(error: unknown): ResolvedError {
  if (isConfigurationError(error)) {
    // LE TAIRE SERAIT LE PIRE : le message d'origine nomme la variable
    // d'environnement manquante et rappelle qu'un rebuild est necessaire.
    console.error('FRONT-10 : configuration du client d’API invalide.', error);
    return {
      message: lookup(ERROR_MESSAGES, 'api_client.configuration.invalid') ?? GENERIC_MESSAGE,
      code: 'api_client.configuration.invalid',
      status: 0,
      requestId: null,
      isUnknownCode: false,
      visibleRequestId: null,
    };
  }

  if (!isApiErrorShape(error)) {
    return {
      message: lookup(ERROR_MESSAGES, 'api_client.error.unrecognized') ?? GENERIC_MESSAGE,
      code: 'api_client.error.unrecognized',
      status: 0,
      requestId: null,
      isUnknownCode: true,
      visibleRequestId: null,
    };
  }

  const known = lookup(ERROR_MESSAGES, error.code);
  const isUnknownCode = known === undefined;
  if (
    isUnknownCode &&
    !error.code.startsWith(DERIVED_CODE_PREFIX) &&
    !reportedCodes.has(error.code)
  ) {
    // Une trace, et pas un silence : un code non traduit passe autrement
    // inapercu -- l'utilisateur voit une phrase generique parfaitement
    // credible, et personne n'apprend qu'il manque une entree.
    reportedCodes.add(error.code);
    console.warn(
      `FRONT-10 : code d'erreur inconnu « ${error.code} » (statut ${String(error.status)}). ` +
        'Ajouter son message a packages/api-client/src/errors/messages.ts.',
    );
  }

  const requestId = typeof error.requestId === 'string' ? error.requestId : null;

  return {
    message: known ?? STATUS_MESSAGES[error.status] ?? GENERIC_MESSAGE,
    code: error.code,
    status: error.status,
    requestId,
    isUnknownCode,
    // 5xx ET l'absence de reponse valent la peine d'un identifiant ; un 4xx est
    // un refus que l'utilisateur peut corriger seul, et l'encombrer d'un
    // identifiant technique le detournerait de ce qu'il a a faire.
    visibleRequestId: error.status >= 500 || error.status === 0 ? requestId : null,
  };
}

/** Une violation de schema, telle que BACK-09 la range sous `details.errors`. */
type ValidationViolation = {
  loc: ReadonlyArray<string | number>;
  msg: string;
  type: string;
};

/** Les segments de `loc` qui nomment l'EMPLACEMENT et non le champ. */
const LOCATION_SEGMENTS = new Set(['body', 'query', 'path', 'header', 'cookie']);

function isViolation(value: unknown): value is ValidationViolation {
  if (typeof value !== 'object' || value === null) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return Array.isArray(candidate.loc) && typeof candidate.type === 'string';
}

/**
 * Repositionne les violations d'un 422 sur les champs du formulaire.
 *
 * LE NOM DU CHAMP SE DEDUIT DE `loc`, dont le premier segment nomme
 * l'emplacement (`body`, `query`...) et non un champ : on le retire, et on
 * joint le reste par un point -- `['body','pets',0,'name']` devient
 * `pets.0.name`. La forme rendue est celle qu'attend `FieldError` de
 * `@repo/ui`.
 *
 * UN 422 METIER REND UN OBJET VIDE, ET C'EST EXACT. Seule la validation de
 * SCHEMA (`http.request.validation_error`) range ses violations sous
 * `details.errors` ; une `ValidationError` du domaine porte un code namespace
 * et des details libres, sans pointeur de champ. L'appelant affiche alors le
 * message au niveau du formulaire, pas sur un champ devine.
 *
 * @param error Ce qu'un `catch` a rendu -- n'importe quoi.
 * @returns Les messages par champ, vide s'il n'y a rien de repositionnable.
 */
export function toFieldErrors(error: unknown): Record<string, Array<{ message: string }>> {
  if (!isApiErrorShape(error)) {
    return {};
  }
  // `typeof` PLUTOT QUE `error.details === null` : la garde structurelle ne
  // verifie que `status` et `code`, si bien qu'un objet SANS `details` du tout
  // faisait lever cette fonction -- alors que sa signature accepte `unknown` et
  // que la documentation promet « n'importe quoi ». Reproduit en revue.
  const details: unknown = error.details;
  if (typeof details !== 'object' || details === null || Array.isArray(details)) {
    return {};
  }
  const violations: unknown = (details as Record<string, unknown>).errors;
  if (!Array.isArray(violations)) {
    return {};
  }

  // UNE `Map`, ET NON UN OBJET LITTERAL. Un champ nomme `__proto__` ou
  // `constructor` -- ce que remonte `extra_forbidden` sur un corps libre --
  // faisait lever `(fieldErrors[path] ??= []).push` : la valeur HERITEE n'etant
  // pas `undefined`, l'affectation ne se faisait pas et `.push` n'existait pas.
  // Le formulaire entier tombait pour un nom de clef. `Object.fromEntries` pose
  // ensuite des proprietes PROPRES, y compris pour ces noms-la.
  const fieldErrors = new Map<string, Array<{ message: string }>>();
  for (const violation of violations) {
    if (!isViolation(violation)) {
      continue;
    }
    const segments = violation.loc.map(String);
    // L'EMPLACEMENT SE RETIRE MEME QUAND IL EST SEUL. `loc: ["body"]` est ce que
    // FastAPI emet pour un corps absent ou illisible : le garder produisait un
    // champ fantome nomme « body », qu'aucun formulaire ne porte, et le message
    // disparaissait de l'ecran. Sans segment restant, la violation appartient au
    // FORMULAIRE et non a un champ -- l'appelant la lira par `resolveApiError`.
    const named = LOCATION_SEGMENTS.has(segments[0] ?? '') ? segments.slice(1) : segments;
    const path = named.join('.');
    if (path === '') {
      continue;
    }
    const message = lookup(VALIDATION_TYPE_MESSAGES, violation.type) ?? GENERIC_FIELD_MESSAGE;
    const existing = fieldErrors.get(path);
    if (existing === undefined) {
      fieldErrors.set(path, [{ message }]);
    } else {
      existing.push({ message });
    }
  }
  return Object.fromEntries(fieldErrors);
}
