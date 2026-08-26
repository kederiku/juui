"""Adaptateurs sortants du module identity (BACK-17, transport revu par BACK-22).

Ce que le module APPELLE, par opposition a `db/` -- ce qu'il persiste -- et a
`api/` -- ce par quoi on l'appelle. Deux adaptateurs y vivent :

- `redis_otp_store.py` -- le magasin des codes de verification et de leurs
  quotas, adosse a Redis, ECHOUANT FERME ;
- `email_otp_sender.py` -- la composition du message de verification, remise
  confiee au port `EmailTransport` de `shared/`.

CE QUE BACK-22 A REPRIS, ET CE QU'IL A LAISSE
BACK-17 avait ecrit ici son propre dialogue SMTP, a titre provisoire et en le
declarant. Le dialogue est parti dans `shared/infrastructure/clients/` derriere
un port technique (ADR-0022) ; ce qui reste est la composition du message, qui
appartient bien a identity. Le port `OtpSender` n'a pas bouge, comme promis.

CE QUI N'A PAS EU LIEU, ET POURQUOI : l'OTP ne transite PAS par le module
`notifications`. Un evenement de notification passe par la file, ou tout argument
voyage en clair dans un stream sans TTL ; un code de verification est un secret
engendre dans le worker et remis depuis le worker (ADR-0020). La regle qui compte
survit telle quelle : un OTP est TRANSACTIONNEL, il part quelles que soient les
preferences de notification -- ce que la distinction posee par BACK-22 nomme
desormais explicitement.
"""
