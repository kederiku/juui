import { NextResponse } from 'next/server';

import { SESSION_COOKIE_NAME, sessionFromToken } from '@/lib/session';

import type { NextRequest } from 'next/server';

/**
 * Redirection vers la connexion par defaut (FRONT-03).
 *
 * Le back-office est un espace entierement prive : rien n'y est accessible sans
 * session. La regle est donc inversee par rapport a un site ordinaire -- ce
 * n'est pas le contenu protege qui se declare, c'est le contenu PUBLIC, et il se
 * reduit a la page de connexion.
 *
 * POURQUOI `proxy.ts` ET NON `middleware.ts`
 * Next 16 a renomme la convention. Un fichier `middleware.ts` fonctionne encore,
 * mais fait avertir CHAQUE build -- exactement le genre de bruit permanent que
 * FRONT-01 a refuse en desactivant `agentRules`. Le fichier porte donc le nom
 * courant, et la fonction exportee s'appelle `proxy` : Next cherche `mod.proxy`
 * dans ce fichier-la, et echouerait sur un export nomme `middleware`.
 *
 * FRONT-07 ecrit `frontend/<app>/middleware.ts` dans son perimetre. C'est le
 * meme fichier sous son ancien nom : il trouvera ici la fonction a completer,
 * pas une application a re-router.
 *
 * CE QUE CE FICHIER NE FAIT PAS
 * Il ne verifie pas le jeton. `sessionFromToken` se borne a constater la
 * presence du cookie (voir `lib/session.ts`) : la validation de signature, le
 * rafraichissement et la deconnexion sont l'objet de FRONT-07.
 */
export function proxy(request: NextRequest) {
  const session = sessionFromToken(request.cookies.get(SESSION_COOKIE_NAME)?.value);

  if (session) {
    return NextResponse.next();
  }

  const loginUrl = new URL('/login', request.url);
  const requested = `${request.nextUrl.pathname}${request.nextUrl.search}`;

  /*
   * L'adresse demandee est conservee pour y revenir apres connexion -- ce que
   * FRONT-07 exploitera. Pas de `next=/` : l'accueil est deja la destination par
   * defaut, et le parametre n'apprendrait rien.
   */
  if (requested !== '/') {
    loginUrl.searchParams.set('next', requested);
  }

  return NextResponse.redirect(loginUrl);
}

export const config = {
  /*
   * Tout, sauf quatre exceptions.
   *
   * `login` d'abord, sans quoi la redirection se redirigerait elle-meme -- le
   * navigateur s'arrete au bout d'une vingtaine de sauts, sur une erreur qui ne
   * nomme pas sa cause.
   *
   * `robots.txt` ensuite, et c'est moins evident : ce fichier DOIT etre servi.
   * Un robot redirige vers une page de connexion n'y lit aucune directive, donc
   * n'apprend pas qu'il doit s'abstenir -- le `disallow` de `app/robots.ts`
   * serait ecrit pour personne.
   *
   * Les deux dernieres sont les fichiers statiques et les images optimisees :
   * les faire transiter par le middleware n'apporte rien et coute une execution
   * par requete.
   */
  matcher: ['/((?!login|_next/static|_next/image|favicon.ico|robots.txt).*)'],
};
