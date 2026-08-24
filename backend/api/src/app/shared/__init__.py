"""Noyau partage des modules metier -- et non un module metier de plus.

`shared/` porte ce dont PLUSIEURS modules ont besoin sans que cela appartienne
au metier d'aucun : la racine des erreurs de domaine, les ports techniques
(cache, stockage de fichiers, jetons), et le socle de persistance et d'API.

Une seule regle, et elle est a sens unique :

    modules/  ->  shared/     autorise
    shared/   ->  modules/    INTERDIT

Un import de `shared` vers un module signifierait que le noyau connait un
contexte metier particulier, et le premier module en entrainerait un deuxieme :
c'est ainsi qu'un noyau partage devient le fourre-tout dont plus personne ne
peut rien retirer.

A ne pas confondre avec `app.core`, qui porte la configuration (BACK-03) puis la
journalisation (BACK-11) : ce sont des reglages du PROCESSUS, pas des briques
d'architecture. Le ticket BACK-04 demande explicitement de laisser `core/` en
place plutot que de le fondre ici.
"""
