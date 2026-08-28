/**
 * FRONT-10 -- Preuve que la traduction des erreurs tient ses regles.
 *
 * CE QUE CE PROGRAMME PROUVE, ET POURQUOI IL EXISTE
 * Quatre des six criteres d'acceptation du ticket portent sur des proprietes
 * qu'aucun typage ne verifie : un code inconnu doit produire un message et non
 * un ecran vide, le message brut du backend ne doit jamais sortir, un 404 doit
 * se dire « introuvable » et jamais « vous n'avez pas les droits », et
 * l'inscription ne doit rien reveler d'une adresse deja utilisee. La carte dit
 * « (test) » en toutes lettres.
 *
 * MEME FORME QUE `verify-query-keys.ts`, ET POUR LA MEME RAISON : le depot n'a
 * aucun runner de test frontend -- Vitest est le perimetre de FRONT-06, la CI
 * frontend celui de QA-02, et les poser ici serait rendre a leur place les
 * arbitrages qui font leur contenu. Node 24 efface les types a la volee :
 * `node scripts/verify-errors.ts` execute ce fichier et les modules qu'il
 * verifie TELS QUELS, sans compilation, sans pile demarree, sans dependance.
 *
 * L'IMPORT PASSE PAR LE NOM DU PACKAGE, jamais par `../src/` : Node exige une
 * extension explicite, que les imports relatifs du depot n'ecrivent jamais, et
 * l'auto-reference fait lire la carte `exports`, qui la porte. Ce fichier reste
 * donc hors du `include` de `tsconfig.verify.json`, dont la resolution `node10`
 * ne sait pas lire cette carte.
 *
 * CE QU'IL NE PROUVE PAS : le RENDU. Aucun des deux composants de
 * `@repo/ui/components/error/` n'est monte ici -- il faudrait un DOM, donc
 * QA-02. La preuve de l'affichage est a l'oeil, et la page « Erreurs a
 * l'ecran » du site de documentation dit comment la produire.
 */

/* eslint-disable no-console -- la sortie console EST le produit de ce programme :
   il n'a pas d'autre facon de rendre son verdict a qui lance `pnpm test`. Meme
   arbitrage que verify-query-keys.ts. */

import {
  ApiConfigurationError,
  ApiError,
  CLIENT_ERROR_CODES,
} from '@repo/api-client/errors/api-error';
import {
  ERROR_MESSAGES,
  GENERIC_MESSAGE,
  MESSAGES_BY_MODULE,
  resolveApiError,
  STATUS_MESSAGES,
  toFieldErrors,
} from '@repo/api-client/errors/messages';
import type { ResolvedError } from '@repo/api-client/errors/messages';

/** Un controle nomme, tel qu'il s'affiche a l'ecran. Meme forme que verify.ts. */
type Check = { name: string; run: () => string };

/** Fabrique une ApiError comme le mutator en leve une. */
function apiError(init: {
  status: number;
  code: string;
  message?: string;
  details?: Record<string, unknown> | null;
  requestId?: string | null;
}): ApiError {
  return new ApiError({
    status: init.status,
    code: init.code,
    message: init.message ?? 'message de journal, jamais affiche',
    details: init.details ?? null,
    requestId: init.requestId ?? null,
  });
}

/** Capture ce qu'un appel ecrit sur `console.warn`, et rend la console intacte. */
function captureWarnings(run: () => void): string[] {
  const captured: string[] = [];
  const original = console.warn;
  console.warn = (...args: unknown[]) => {
    captured.push(args.map(String).join(' '));
  };
  try {
    run();
  } finally {
    console.warn = original;
  }
  return captured;
}

/** Meme chose pour `console.error`, que la branche de configuration emprunte. */
function captureErrors(run: () => void): string[] {
  const captured: string[] = [];
  const original = console.error;
  console.error = (...args: unknown[]) => {
    captured.push(args.map(String).join(' '));
  };
  try {
    run();
  } finally {
    console.error = original;
  }
  return captured;
}

const FORBIDDEN_IN_NOT_FOUND = ['droit', 'autorisation', 'permission'];

/** Une violation de schema, telle que BACK-09 la range sous `details.errors`. */
function violation(loc: Array<string | number>): {
  loc: Array<string | number>;
  msg: string;
  type: string;
} {
  return { loc, msg: 'Field required', type: 'missing' };
}

const checks: Check[] = [
  {
    name: 'un code inconnu tombe sur un repli ET se journalise',
    run: () => {
      // TOUT PASSE PAR LA CAPTURE, y compris ce qui ne l'examine pas : un
      // avertissement laisse filer ici se melerait au verdict du programme.
      let resolved: ResolvedError | undefined;
      let orphan: ResolvedError | undefined;
      const warnings = captureWarnings(() => {
        resolved = resolveApiError(apiError({ status: 409, code: 'identity.gadget.exploded' }));
        // Un statut inconnu LUI AUSSI, donc sans repli : c'est le dernier filet.
        orphan = resolveApiError(apiError({ status: 418, code: 'x.y.z' }));
      });
      if (resolved?.isUnknownCode !== true) {
        throw new Error("isUnknownCode n'a pas ete leve");
      }
      if (resolved.message !== STATUS_MESSAGES[409]) {
        throw new Error(`repli attendu sur le statut, recu ${JSON.stringify(resolved.message)}`);
      }
      if (orphan?.message !== GENERIC_MESSAGE) {
        throw new Error(`repli generique attendu, recu ${JSON.stringify(orphan?.message)}`);
      }
      if (warnings.length !== 2 || !warnings[0]?.includes('identity.gadget.exploded')) {
        throw new Error(`journalisation absente ou muette : ${JSON.stringify(warnings)}`);
      }
      // LA FAMILLE DERIVEE NE SE JOURNALISE PAS, et c'est mesure a l'ecran : un
      // 404 de routage ordinaire ecrivait un avertissement « code inconnu » a
      // chaque affichage, ce qui aurait noye celui qui compte.
      let derived: ResolvedError | undefined;
      const silent = captureWarnings(() => {
        derived = resolveApiError(apiError({ status: 404, code: 'http.request.not_found' }));
      });
      if (silent.length !== 0) {
        throw new Error(`la famille derivee a journalise : ${JSON.stringify(silent)}`);
      }
      if (derived?.message !== STATUS_MESSAGES[404]) {
        throw new Error('un 404 de routage ne tombe pas sur le repli 404');
      }
      return 'repli par statut, puis generique, un avertissement cible, et la famille derivee muette';
    },
  },
  {
    name: 'jamais un ecran vide, quelle que soit l’entree',
    run: () => {
      const pathological: unknown[] = [
        null,
        undefined,
        {},
        '',
        'une chaine',
        new Error('erreur quelconque'),
        new DOMException('Aborted', 'AbortError'),
        new ApiConfigurationError('base URL absente'),
        apiError({ status: 0, code: '' }),
        // LES TROIS SUIVANTES SONT DES CLEFS D'`Object.prototype`, et elles ont
        // ete ajoutees apres coup : la premiere version de cette liste ne les
        // portait pas, et la revue a montre qu'un acces indexe nu rendait alors
        // une FONCTION -- ecran vide -- ou un objet, sur lequel React tombait.
        // Le code vient du corps de la reponse, donc de l'exterieur.
        apiError({ status: 500, code: 'constructor' }),
        apiError({ status: 500, code: '__proto__' }),
        apiError({ status: 500, code: 'toString' }),
      ];
      captureWarnings(() => {
        captureErrors(() => {
          // L'INDEX PLUTOT QUE LA VALEUR dans le message d'echec : plusieurs de
          // ces entrees ne se serialisent pas, et une sonde qui leve en
          // fabriquant son propre message d'erreur ne dit plus rien.
          pathological.forEach((value, index) => {
            const resolved = resolveApiError(value);
            if (typeof resolved.message !== 'string' || resolved.message.trim() === '') {
              throw new Error(
                `entree ${String(index)} : message de type ${typeof resolved.message}`,
              );
            }
          });
        });
      });
      return `${String(pathological.length)} entrees pathologiques, toutes traduites`;
    },
  },
  {
    name: 'le message du backend ne ressort jamais a l’ecran',
    run: () => {
      const leak = 'FUITE : SELECT * FROM accounts WHERE id = 42';
      // Un code CONNU d'abord : c'est la table qui doit gagner, pas le corps.
      const known = resolveApiError(
        apiError({ status: 404, code: 'identity.account.not_found', message: leak }),
      );
      if (known.message.includes('FUITE')) {
        throw new Error('le message du backend est ressorti sur un code connu');
      }
      // Puis un code INCONNU : c'est la que la tentation existe, le repli
      // paraissant moins precis que ce que le serveur a ecrit.
      let unknown = known;
      captureWarnings(() => {
        unknown = resolveApiError(apiError({ status: 404, code: 'a.b.c', message: leak }));
      });
      if (unknown.message.includes('FUITE')) {
        throw new Error('le message du backend est ressorti sur un code inconnu');
      }
      return 'code connu et code inconnu : la table et le repli, jamais le corps';
    },
  },
  {
    name: 'un 404 se dit « introuvable », jamais un refus de droit',
    run: () => {
      // LA SONDE NE SE PRONONCE QUE SUR LE 404. Le vocabulaire du droit est
      // legitime sur un 403 (`shared.resource.forbidden`) : le backend ne
      // repond 403 que pour une ressource dont l'appelant a le droit de savoir
      // qu'elle existe. C'est le 404 qui porte la non-divulgation (ADR-0013).
      const fallback = STATUS_MESSAGES[404] ?? '';
      if (!fallback.toLowerCase().includes('introuvable')) {
        throw new Error(`le repli 404 ne dit pas « introuvable » : ${JSON.stringify(fallback)}`);
      }
      const suspects = Object.entries(ERROR_MESSAGES)
        .filter(([code]) => code.endsWith('.not_found'))
        .concat([['(repli 404)', fallback]]);
      for (const [code, message] of suspects) {
        const lowered = message.toLowerCase();
        const found = FORBIDDEN_IN_NOT_FOUND.find((word) => lowered.includes(word));
        if (found !== undefined) {
          throw new Error(`${code} parle de « ${found} » : ${JSON.stringify(message)}`);
        }
        if (!lowered.includes('introuvable')) {
          throw new Error(`${code} ne dit pas « introuvable » : ${JSON.stringify(message)}`);
        }
      }
      return `${String(suspects.length)} messages d'absence, tous « introuvable »`;
    },
  },
  {
    name: 'l’inscription ne revele pas qu’une adresse est deja utilisee',
    run: () => {
      // UNE EGALITE, ET NON UNE INTERDICTION LEXICALE GLOBALE : « existe deja »
      // est la formulation JUSTE pour `shared.resource.already_exists`, qui n'a
      // rien a voir avec la non-divulgation. C'est ce code-ci qui doit rester
      // neutre, et le figer est la seule facon de le dire.
      const expected =
        'Cette inscription n’a pas pu aboutir. Vérifiez vos informations, puis réessayez.';
      const actual = ERROR_MESSAGES['identity.account.email_already_used'];
      if (actual !== expected) {
        throw new Error(`message neutre attendu, recu ${JSON.stringify(actual)}`);
      }
      const lowered = actual.toLowerCase();
      for (const leak of ['déjà utilisé', 'existe déjà', 'already', 'compte existe']) {
        if (lowered.includes(leak)) {
          throw new Error(`le message revele l'existence du compte : « ${leak} »`);
        }
      }
      return "le refus d'inscription reste identique que l'adresse soit libre ou prise";
    },
  },
  {
    name: 'une panne de configuration ne devient pas « reessayez »',
    run: () => {
      let resolved = resolveApiError(new Error('placeholder'));
      const errors = captureErrors(() => {
        resolved = resolveApiError(new ApiConfigurationError('NEXT_PUBLIC_API_URL absente'));
      });
      if (resolved.message === GENERIC_MESSAGE) {
        throw new Error('la panne de configuration est tombee dans le repli generique');
      }
      if (resolved.visibleRequestId !== null) {
        throw new Error("aucune requete n'est partie : il n'y a pas d'identifiant a montrer");
      }
      if (errors.length !== 1 || !errors[0]?.includes('FRONT-10')) {
        throw new Error(`le message d'origine n'est pas parti au journal : ${String(errors)}`);
      }
      return 'message dedie, aucun « reessayez », et la cause reelle au journal';
    },
  },
  {
    name: 'le request_id ne s’annonce que quand il existe et qu’il sert',
    run: () => {
      const cases: Array<[string, number, string | null, boolean]> = [
        ['500 avec identifiant', 500, 'abc123', true],
        ['503 avec identifiant', 503, 'abc123', true],
        // LE CAS QUI COMPTE : un vrai 500 sort hors CORS, le navigateur le rend
        // comme un echec reseau, et l'identifiant est perdu (ecart BACK-11).
        ['transport sans identifiant', 0, null, false],
        ['500 sans identifiant', 500, null, false],
        ['404 avec identifiant', 404, 'abc123', false],
        ['429 avec identifiant', 429, 'abc123', false],
      ];
      for (const [label, status, requestId, expected] of cases) {
        const resolved = resolveApiError(
          apiError({ status, code: 'shared.resource.not_found', requestId }),
        );
        const shown = resolved.visibleRequestId !== null;
        if (shown !== expected) {
          throw new Error(`${label} : visibleRequestId vaut ${String(resolved.visibleRequestId)}`);
        }
      }
      return `${String(cases.length)} cas : 5xx et transport oui, 4xx non, jamais sans identifiant`;
    },
  },
  {
    name: 'un 422 de schema se repose sur les bons champs, en francais',
    run: () => {
      const violations = [
        { loc: ['body', 'email'], msg: 'Field required', type: 'missing' },
        { loc: ['body', 'pets', 0, 'name'], msg: 'String too short', type: 'string_too_short' },
        { loc: ['body', 'intrus'], msg: 'Extra inputs are not permitted', type: 'extra_forbidden' },
        { loc: ['body', 'age'], msg: 'Unheard of', type: 'type_venu_du_futur' },
      ];
      const fields = toFieldErrors(
        apiError({
          status: 422,
          code: 'http.request.validation_error',
          details: { errors: violations },
        }),
      );
      const paths = Object.keys(fields).sort();
      const expected = ['age', 'email', 'intrus', 'pets.0.name'];
      if (JSON.stringify(paths) !== JSON.stringify(expected)) {
        throw new Error(
          `chemins attendus ${JSON.stringify(expected)}, recus ${JSON.stringify(paths)}`,
        );
      }
      // Le `msg` de Pydantic est en ANGLAIS et vient du serveur : il ne doit
      // apparaitre dans aucune valeur rendue.
      const rendered = JSON.stringify(fields);
      for (const violation of violations) {
        if (rendered.includes(violation.msg)) {
          throw new Error(`le msg anglais « ${violation.msg} » est ressorti`);
        }
      }
      // Un 422 METIER n'a pas de pointeur de champ : rien a reposer.
      const business = toFieldErrors(apiError({ status: 422, code: 'shared.password.too_short' }));
      if (Object.keys(business).length !== 0) {
        throw new Error('un 422 metier a produit des erreurs de champ');
      }

      // TROIS FORMES HOSTILES, TOUTES REPRODUITES EN REVUE, TOUTES LEVAIENT.
      // `loc: ["body"]` est ce que FastAPI emet pour un corps absent : il
      // fabriquait un champ fantome « body ». Un champ nomme `__proto__` faisait
      // lever `.push`. Et un objet sans `details` faisait lever la lecture.
      const alone = toFieldErrors(
        apiError({ status: 422, code: 'c', details: { errors: [violation(['body'])] } }),
      );
      if (Object.keys(alone).length !== 0) {
        throw new Error(`loc=['body'] a produit ${JSON.stringify(alone)}`);
      }
      const inherited = toFieldErrors(
        apiError({
          status: 422,
          code: 'c',
          details: { errors: [violation(['body', '__proto__'])] },
        }),
      );
      if (!Object.hasOwn(inherited, '__proto__')) {
        throw new Error("un champ nomme __proto__ n'est pas ressorti en propriete propre");
      }
      const noDetails = toFieldErrors({ status: 422, code: 'c' });
      if (Object.keys(noDetails).length !== 0) {
        throw new Error('un objet sans details a produit des erreurs de champ');
      }
      return 'emplacement retire meme seul, chemin imbrique, type inconnu replie, formes hostiles digerees';
    },
  },
  {
    name: 'chaque code fabrique par le client a son message',
    run: () => {
      // LES DEUX FICHIERS SE RECOPIENT, ET C'EST ASSUME : `messages.ts` ne peut
      // rien importer en valeur sans cesser d'etre executable par Node. Cette
      // sonde est ce qui remplace l'import -- sans elle, un code fabrique par le
      // client tomberait sur le repli generique sans que personne ne le voie.
      const missing = Object.values(CLIENT_ERROR_CODES).filter(
        (code) => !Object.hasOwn(ERROR_MESSAGES, code),
      );
      if (missing.length > 0) {
        throw new Error(`codes sans message : ${missing.join(', ')}`);
      }
      return `${String(Object.keys(CLIENT_ERROR_CODES).length)} codes client, tous traduits`;
    },
  },
  {
    name: 'la fusion des huit enregistrements n’ecrase aucune clef',
    run: () => {
      const total = MESSAGES_BY_MODULE.reduce(
        (count, record) => count + Object.keys(record).length,
        0,
      );
      const merged = Object.keys(ERROR_MESSAGES).length;
      if (total !== merged) {
        throw new Error(`${String(total - merged)} clef(s) ecrasee(s) a la fusion`);
      }
      // Toute clef doit ressembler a un code : `<module>.<ressource>.<erreur>`.
      const malformed = Object.keys(ERROR_MESSAGES).filter(
        (code) => !/^[a-z_]+(\.[a-z_]+){2}$/.test(code),
      );
      if (malformed.length > 0) {
        throw new Error(`clefs hors gabarit : ${malformed.join(', ')}`);
      }
      return `${String(merged)} messages, aucune collision, tous au gabarit du backend`;
    },
  },
];

function main(): void {
  console.log('FRONT-10 : verification de la traduction des erreurs.\n');

  let failed = 0;
  for (const check of checks) {
    try {
      const detail = check.run();
      console.log(`  OK   ${check.name}\n       ${detail}`);
    } catch (error) {
      failed += 1;
      const reason = error instanceof Error ? error.message : String(error);
      console.error(`  ECHEC ${check.name}\n       ${reason}`);
    }
  }

  console.log('');
  if (failed > 0) {
    console.error(`FRONT-10 : ${String(failed)} controle(s) en echec.`);
    process.exitCode = 1;
    return;
  }
  console.log(`FRONT-10 : ${String(checks.length)} controles passes.`);
}

main();
