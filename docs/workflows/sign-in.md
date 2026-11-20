# Sign-in — UI → backend workflow

## Example used

**alice** (adjuster) signs in to the console on AWS with her Cognito password, then **frank**
(an adjuster suspended in ClaimSense) tries the same.

Source tests: `api/tests/test_cognito.py` (17 tests: accepted token, frank 403, wrong key, other pool,
other app client, ID token, expired, group mismatch, HS256 token claiming Cognito's issuer,
development tokens refused once Cognito is on).

```text
alice + correct password  → Cognito access token → GET /api/v1/me 200 → /claims (6 claims)
alice + wrong password    → "Wrong user name or password."   (Cognito NotAuthorizedException)
frank + correct password  → Cognito says yes → GET /api/v1/me 403 → "Your account may not use ClaimSense."
claimsense-batch          → not in the pool → "Wrong user name or password."
```

**Important architectural note:** the password is checked by **Amazon Cognito**, but whether the
person may use ClaimSense is decided by **the data API**: the token's user must exist in
`claimsense.users`, be active, and have the same group as in Cognito. The console decides nothing
itself. Locally (no Cognito settings) the same form uses the development sign-in instead.

---

## 1. User action in the browser

The user opens `/login`, types a user name and password and clicks **Sign in**.

| Step | Function | File |
|---|---|---|
| Page rendered (server) | `LoginPage()` reads `cognitoConfig()` to choose the Cognito or development form | `platform/web/src/app/login/page.tsx` |
| Form | `LoginForm({ cognito })`: password field only in Cognito mode | `platform/web/src/app/login/LoginForm.tsx` |
| Submit | form posts to the server action `loginAction` | `platform/web/src/app/login/actions.ts` |

## 2. The console's server checks the password with Cognito

`loginAction` runs on the console's server, never in the browser.

| Step | Function | File |
|---|---|---|
| Is Cognito on? | `cognitoConfig()`: on when `CLAIMSENSE_COGNITO_POOL_ID` and `CLAIMSENSE_COGNITO_CLIENT_ID` are set; region = the pool id's prefix | `platform/web/src/lib/cognito.ts` |
| Check the password | `cognitoSignIn(config, username, password)`: `POST https://cognito-idp.us-east-1.amazonaws.com/` with `X-Amz-Target: AWSCognitoIdentityProviderService.InitiateAuth`, `AuthFlow: USER_PASSWORD_AUTH` | `platform/web/src/lib/cognito.ts` |
| Map Cognito errors | `NotAuthorizedException` / `UserNotFoundException` → "Wrong user name or password." (the pool hides whether a user exists); `PasswordResetRequiredException`, `TooManyRequestsException`, a challenge → their own messages | `platform/web/src/lib/cognito.ts` |

Cognito's settings (`deploy/cognito/setup.sh`): app client `claimsense-console` with no secret,
`ALLOW_USER_PASSWORD_AUTH` and refresh; access token 8 hours; no self sign-up; no MFA (for now);
passwords of 12+ characters with upper and lower case, a number and a symbol.

## 3. The data API decides who this is

| Step | Function | File |
|---|---|---|
| Ask the API | `whoIs(accessToken)`: `GET /api/v1/me` with `Authorization: Bearer <token>` | `platform/web/src/lib/claimsense.ts` |
| Route | `me()` → `require_user(authorization, "me")` | `api/src/claimsense_api/main.py` |
| Read the header | `read_bearer_token()` | `api/src/claimsense_api/auth.py` |
| Pick the check by issuer | `verify_token()`: reads `iss` unverified; Cognito's issuer → RS256 only; our own issuers → HS256 only | `api/src/claimsense_api/auth.py` |
| Verify | `verify_cognito_token()`: signature with the pool's public key (`cognito_key()`, cached by key id, from `CLAIMSENSE_COGNITO_JWKS` on Lambda or the pool's JWKS URL), issuer, expiry, `token_use == "access"`, `client_id`; then `sub := username` | `api/src/claimsense_api/auth.py` |
| Look up the person | `get_user()`: row in `claimsense.users` (unknown → 401); Cognito group must equal `user_group` (mismatch → 401); `status != active` → `InactiveUser` (403) | `api/src/claimsense_api/auth.py` |
| Rate limit | `allow_request(user_id)` (per user per minute, counted in PostgreSQL) | `api/src/claimsense_api/ratelimit.py` |
| Audit | `log_audit("me", "allow" or "deny", …)` → `claimsense.audit_log` | `api/src/claimsense_api/audit.py` |

For alice: `{"user_id": "alice", "full_name": "Alice Tran", "group": "adjuster"}`. For frank: 403, and
the console shows "Your account may not use ClaimSense."

## 4. Session cookie and redirect

| Step | Function | File |
|---|---|---|
| Keep the token | `setSession({ token, userId, fullName, group })`: cookie `claimsense_session`, **httpOnly**, SameSite=Lax, 8 hours; `Secure` unless `CLAIMSENSE_COOKIE_SECURE=0` (the EC2 console is plain HTTP) | `platform/web/src/lib/session.ts` |
| Go to the queue | `redirect("/claims")` | `platform/web/src/app/login/actions.ts` |
| Every later page | `requireSession()` → `/login` if there is no cookie; `apiGet()` adds the token on the server | `platform/web/src/lib/auth.ts`, `platform/web/src/lib/claimsense.ts` |

Page scripts can never read the token, and the password is never stored or sent to the data API.

## 5. Sign-out

| Step | Function | File |
|---|---|---|
| Click **Sign out** | a form posting to `/api/logout` | `platform/web/src/components/Sidebar.tsx` |
| Clear and redirect | `clearSession()`, then `303` with the relative `Location: /login`, so the browser stays on the host it used (EC2 DNS, a tunnel, localhost) | `platform/web/src/app/api/logout/route.ts` |

The access token itself stays valid until it expires (the API checks tokens offline). Shorter tokens
with refresh are the production fix (`DECISIONS.md`).

## The development sign-in (locally)

With no Cognito settings, `loginAction` calls `devLogin(userId)` → `POST /api/v1/dev/login`
(`dev_login()` in `main.py`): only when `CLAIMSENSE_DEV_LOGIN=1`, never for the batch account, and it
issues an HS256 token signed with `CLAIMSENSE_JWT_SECRET`. Once Cognito is configured, `get_user()`
refuses a **person's** development token (`dev_tokens_for_people()`), so a leaked secret cannot be used
to act as alice; the batch account and agents' OBO tokens are not affected.

## Call chain at a glance

```text
LoginForm (browser)
  → loginAction (console server)
      → cognitoSignIn → Cognito InitiateAuth (USER_PASSWORD_AUTH) → AccessToken
      → whoIs → GET /api/v1/me
                  → require_user → get_user → verify_token → verify_cognito_token → cognito_key
                                             → claimsense.users (exists, group matches, active)
                  → allow_request → log_audit
      → setSession (httpOnly cookie) → redirect /claims
```
