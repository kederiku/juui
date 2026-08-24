"""Unite de travail du module identity -- a livrer par BACK-06a.

Le fichier est cree par BACK-04 pour fixer sa place : a la RACINE du module, et
non dans une couche. L'unite de travail n'appartient ni au domaine (elle
manipule une transaction) ni tout a fait a l'infrastructure (elle expose les
depots au cas d'usage) : elle est le point d'assemblage du module.

CE QUE BACK-06a APPORTERA ICI
Une `IdentityUnitOfWork`, gestionnaire de contexte asynchrone exposant
`commit()`, `rollback()` et les depots du module en attributs :

    async with uow:
        account = await uow.accounts.get(account_id)
        account.verify_email()
        await uow.accounts.save(account)
        await uow.commit()

UNE UNITE DE TRAVAIL PAR MODULE, et jamais une unite globale. Ce qu'on ne peut
pas placer dans une seule transaction devient alors une frontiere VISIBLE --
`identity` et `organization` ne partagent pas leur atomicite -- plutot qu'une
dette invisible que le premier incident revelera.

Le rollback est automatique si le bloc se termine sans `commit` explicite ou sur
exception : oublier de valider ne doit jamais laisser une transaction ouverte.
"""
