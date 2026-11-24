---
title: Troubleshooting Sign-in Problems
doc_type: troubleshooting
tier: all
---

## Before you start

Most Nimbus sign-in problems are caused by a mistyped password, an expired session, a lost two-factor device or a temporary account lock. Before trying the steps below, check that you are signing in at the correct Nimbus workspace address, that Caps Lock is off, and that your browser allows cookies for Nimbus. If you use a browser password manager, check that it is filling in the password for the right account.

## Resetting a forgotten password

To reset a forgotten Nimbus password:

1. On the Nimbus sign-in page, select Forgot password.
2. Enter the email address on your Nimbus account and select Send reset link.
3. Open the password reset email from Nimbus and select the reset link. The reset link expires after 1 hour and can be used only once.
4. Choose a new password of at least 12 characters. Nimbus does not accept any of your last 5 passwords.
5. Sign in with the new password. Resetting a password signs you out of all other sessions.

If the reset email does not arrive within 10 minutes, check your spam or junk folder and confirm you entered the email address used on the account. If your organisation signs in through SSO, the Forgot password link does not apply; see the SSO section of this guide instead.

## Account locked after failed sign-in attempts

Nimbus locks an account for 15 minutes after 5 failed sign-in attempts in a row. The lock protects the account from password-guessing attacks. While the account is locked, even the correct password is refused. To recover from an account lock:

1. Wait 15 minutes from the last failed attempt. The lock lifts automatically.
2. If you are not sure of the password, reset it using the Forgot password link instead of guessing again. A password reset does not lift the current lock early, but it prevents another lock.
3. Sign in again with the correct password.

If the account locks repeatedly when you have not tried to sign in, someone else may be trying to access it. Reset your password and contact support.

## Two-factor authentication lockout

If two-factor authentication (2FA) is turned on and you cannot get a 2FA code, for example because your authenticator device was lost or replaced:

1. On the 2FA screen, select Use a backup code and enter one of the 10 backup codes you saved when you turned on 2FA. Each backup code works once.
2. After signing in, go to Account, then Security, and set up 2FA again on your new device. Generate and save a new set of backup codes.

If you do not have a backup code, a workspace admin can reset 2FA for your user from the admin console under Users. If you are the only workspace owner and have no backup codes, open a support ticket. Nimbus support verifies ownership with your account ID and support PIN, then confirms by email before removing 2FA. The support assistant cannot remove 2FA directly.

## SSO and SAML sign-in {tier=enterprise}

Enterprise plan workspaces can require single sign-on (SSO) through a SAML 2.0 identity provider. When SSO is required, users sign in through the identity provider and do not have a separate Nimbus password. If SSO sign-in fails:

1. Confirm that you can sign in to your identity provider directly. If you cannot, contact your own IT team.
2. Check with your IT team that your user is assigned to the Nimbus application in the identity provider.
3. If you see a "SAML response invalid" error, ask your Nimbus admin to check that the identity provider's signing certificate in Nimbus matches the current certificate. Expired certificates are the most common cause of SSO failures.
4. Check that the email address sent by the identity provider matches your Nimbus account email exactly.

Enterprise admins can always sign in with a recovery owner account that bypasses SSO, so that SSO settings can be fixed if the identity provider is unavailable. Enterprise customers with SSO problems affecting the whole workspace should report them as a severity 1 issue by phone.

## Session and browser problems

If you are signed in but keep being sent back to the sign-in page, clear the browser cache and cookies for Nimbus, turn off browser extensions that block cookies, and try a private browsing window. Nimbus sessions expire after 30 days of inactivity, or sooner if your workspace admin has set a shorter session policy.

## When to contact support

Contact Nimbus support if none of the steps above work. Include your account ID, the email you are signing in with, the time of the failed attempt and any error message. Never send your password or a 2FA code to support.
