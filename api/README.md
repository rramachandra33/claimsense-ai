# ClaimSense data API

The single gatekeeper in front of the client-system data. Every request goes through the same three
steps, in this order:

1. **Who is calling?** `auth.py` verifies the token (development tokens now, Amazon Cognito later)
   and loads the user from `claimsense.users`. Identity comes only from the token.
2. **May they see this?** `access.py` applies the confirmed role table
   (`docs/ClaimSense-AI-Users-and-Access-Rules.pdf`) before any agent runs.
3. **Audit.** `audit.py` writes one row for every call, allowed or denied, with the full reason.

Refusals are generic: an unknown claim and a forbidden one get the same 403, and the reason is kept in
the audit log only. The four modules are Python ports of the Week 15 sample's `auth.ts`, `scope.ts`,
`audit.ts` and `respond.ts`.

## Run

```bash
make up                         # database (from the repo root)
export CLAIMSENSE_JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
make api                        # http://localhost:8000/docs
make token USER=alice           # a development token for alice
make api-test                   # access tests (7 users x 20 claims and the refusal cases)
```

## Routes so far

| Route | What it returns |
|---|---|
| `GET /api/v1/health` | Service and database status (no token needed) |
| `GET /api/v1/me` | The calling user |
| `GET /api/v1/claims` | Only the claims the caller may read |
| `GET /api/v1/claims/{id}` | One claim, after the access check |
| `GET /api/v1/claims/{id}/policy` | The claim's policy, reached only through the claim; never returns holder names |
| `GET /api/v1/claims/{id}/documents` | The claim's document list (no text) |
| `GET /api/v1/documents/{id}` | One document with its text; text is null unless OCR is Completed (CLS-DOC-009) |
| `GET /api/v1/clauses?q=…&top_k=4` | Policy-manual search over `clause_index` only, so a quarantined clause can never come back; matches any word, best first |

Next: the claim-note write with idempotency; then the MCP server.
