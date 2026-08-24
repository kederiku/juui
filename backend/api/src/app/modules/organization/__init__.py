"""Groupes, cliniques et appartenances -- module a livrer par BACK-16.

Paquet cree par BACK-04 pour poser la frontiere des le depart. `identity` repond
a « peux-tu prouver qui tu es » ; celui-ci repond a « dans quelle structure ce
compte travaille-t-il, et affecte ou ». Deux questions distinctes, donc deux
modules -- les fondre reviendrait a coller au compte un `group_id` immuable, ce
qu'un veterinaire remplacant intervenant dans plusieurs groupes contredit des le
premier jour.

CE QUE BACK-16 APPORTERA ICI
Les entites `Groupe` (LE tenant, frontiere d'isolation), `Clinique` (perimetre
de travail, pas frontiere de securite), `Appartenance` et `Affectation` (deux
relations N:M DATEES), leur persistance, et surtout les TROIS PORTS qui seront
sa seule surface publique : appartenances actives d'un compte, role dans un
groupe donne, affectations dans le groupe actif.

Aucun autre module n'accedera a ses tables.
"""
