# ClaimSense console (`platform/web`)

The adjuster console, a Next.js app adapted from the Week 15 sample's Ops Console (layout, sidebar,
panels and styling kept; the bank pages and its built-in API removed).

**It never touches the database and never decides access.** Every page calls the ClaimSense data API
(`api/`) with the signed-in user's token, server-side, and shows what the API returns, including its
generic refusals.

## Pages

| Page | Shows |
|---|---|
| `/login` | Development sign-in by user id (Amazon Cognito replaces it in deployment) |
| `/claims` | The claims you may work on (the API filters them by your role) |
| `/claims/{id}` | The claim, its policy (no holder names) and its documents |
| `/documents/{id}` | One document's text; a notice instead while OCR is pending (CLS-DOC-009) |
| `/clauses` | Search the AutoSure policy manual, the same search the agents use |

## Run locally

```bash
make up                                                     # database
export CLAIMSENSE_JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
CLAIMSENSE_DEV_LOGIN=1 make api                             # data API on :8000, dev sign-in on
make web                                                    # console on http://localhost:3100
```

| Variable | Default | Meaning |
|---|---|---|
| `CLAIMSENSE_API_URL` | `http://localhost:8000` | Where the data API runs |

The session cookie is httpOnly and holds the API-issued token; page scripts cannot read it.
