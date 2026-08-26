"""Adaptateurs sortants du module identity (BACK-17).

Ce que le module APPELLE, par opposition a `db/` -- ce qu'il persiste -- et a
`api/` -- ce par quoi on l'appelle. Deux adaptateurs y vivent :

- `redis_otp_store.py` -- le magasin des codes de verification et de leurs
  quotas, adosse a Redis, ECHOUANT FERME ;
- `smtp_otp_sender.py` -- la remise du code par courriel.

LE SECOND EST PROVISOIRE, ET IL FAUT LE SAVOIR AVANT D'Y AJOUTER QUOI QUE CE SOIT
Le code SMTP appartient a BACK-22, avec le module `notifications` et son port
d'envoi unique ; BACK-17 en ecrit le minimum vital parce qu'un code qui ne part
pas ne verifie rien, et parce que sa propre carte l'y autorise expressement (« a
defaut, directement l'adaptateur SMTP, a rebrancher ensuite »). Quand BACK-22
existera, `SmtpOtpSender` devra ceder la place a une implementation d'`OtpSender`
qui delegue au `NotificationSender`, en gardant la regle qui compte : un OTP est
TRANSACTIONNEL, il part quelles que soient les preferences de notification.
"""
