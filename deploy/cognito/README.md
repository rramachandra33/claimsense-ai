# Amazon Cognito sign-in

People sign in to the console with a user name and password checked by Amazon Cognito (open
question 9; decided 2026-11-05, see DECISIONS.md).

```
browser ──user name + password──> console (server action) ──InitiateAuth──> Cognito
                                     │  keeps the access token in the httpOnly cookie
                                     └──Bearer access token──> data API (EC2 container or Lambda)
                                            checks the RS256 signature with the pool's public keys,
                                            issuer, client_id, token_use=access; maps the token's
                                            username to claimsense.users; group must match
```

- **Our own sign-in form**, not Cognito's hosted page: Cognito allows plain-HTTP return addresses
  on localhost only, and the EC2 console is plain HTTP.
- **Development sign-in is off on EC2** once the pool exists (`DEV_LOGIN=0`); a person's
  development token is refused too. Locally it stays on. The batch service account keeps its own
  token (it is not a person and is not in the pool), and agents keep their OBO tokens.
- **No MFA** for now; no self sign-up; account recovery by an administrator only.
- **Access tokens last 8 hours**, the console's session. Signing out clears the console's cookie;
  the token itself stays valid until it expires (the API checks tokens offline).
- **The Lambda API is in the VPC with no internet**, so `deploy/lambda/deploy.sh` stores the pool's
  public keys (JWKS) in its environment. Re-run it if Cognito rotates its keys (a Cognito token
  then gets 401 on the Lambda). The EC2 API fetches the keys itself.
- **Roles stay in ClaimSense**: the user's group in Cognito must equal their group in
  `claimsense.users`, and a user suspended there is refused whatever Cognito says.

## Set up

1. As root, once: create the managed policy **`ClaimSenseCognitoDeploy`** from
   `iam/deployer-policy.json` (replace `ACCOUNT`) and attach it to the IAM user `rramachandra33`.
   It may create and set up user pools in this account and region; it cannot delete a pool or a
   user.
2. After a push with a green CI (the images must include the Cognito code), with the EC2 instance
   running:

```bash
export AWS_PROFILE=claimsense
deploy/cognito/setup.sh          # pool, app client, groups, users, passwords; EC2: Cognito on, dev sign-in off
deploy/lambda/deploy.sh          # the Lambda Claims API accepts Cognito tokens
```

The passwords are in `~/.claimsense/cognito-test-users.txt` (yours only). New passwords for
everyone: `RESET_PASSWORDS=1 deploy/cognito/setup.sh`. The pool only (no EC2 change):
`SKIP_EC2=1 deploy/cognito/setup.sh`.

**Back to the development sign-in on EC2** (for example if Cognito is unavailable): set
`DEV_LOGIN=1` and remove the two `COGNITO_` lines in `/opt/claimsense/.env`, then
`docker compose up -d --no-deps api web`.

## Cost

Nothing at this size: the first 10,000 monthly active users are free.

## Tear down

The pool has deletion protection. As root: Cognito → the pool → turn deletion protection off →
delete. Then remove the `COGNITO_` lines from the instance's `.env` (or terminate the instance).
