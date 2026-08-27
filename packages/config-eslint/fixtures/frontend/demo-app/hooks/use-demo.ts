// Un CINQUIEME espace de premier niveau, ni app/ ni features/ : transverse lui
// aussi, et c'est ce que cette fixture prouve. La premiere version du
// generateur enumerait `components` et `lib` en dur, et laissait ce dossier-ci
// lire l'interieur de n'importe quelle feature.
export const useDemo = () => 'demo';
