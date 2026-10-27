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
| `GET /api/v1/clauses?q=…&top_k=4&run_id=…&agent=…` | Policy-manual search over `clause_index` only, so a quarantined clause can never come back; matches any word, best first. With a `run_id`, what came back is saved in `retrieval_log` |
| `POST /api/v1/obo/token` | Pipeline code asks, with the adjuster's token, for one agent's short-lived token (see below) |
| `POST /api/v1/claims/{id}/notes` | The one write: saves the assessment and its append-only claim note together. Needs an `Idempotency-Key` header. Called by pipeline code, never offered to agents as a tool |

### The note write's rules

- A note cites at least one clause, unless it is a DENY with a `deny_reason` (422 `citation_required`).
- Every cited clause must have been returned by clause search in the same run (422 `citation_not_retrieved`).
- Retries are safe: the same key and body return the stored note (200, `Idempotent-Replay: true`);
  the same key with a different body gets 409 `idempotency_conflict`.
- The assessment, note and idempotency key are written in one transaction: all or nothing.

Not yet covered by a test: two identical requests arriving at the same instant (the code falls back to the
replay/409 logic through the database's unique key).

### On-behalf-of (OBO) agent tokens

Agents have no permissions of their own. For each run, pipeline code asks for one token per agent
(`{claim_id, agent, run_id}`), using the adjuster's token; the adjuster must be able to read the claim.
The token acts for the adjuster, is bound to that one claim and run, carries only the agent's scopes,
and lasts 5 minutes.

| Agent | Scopes |
|---|---|
| `reader` | `claim:read`, `documents:read` |
| `coverage` | `claim:read`, `policy:read`, `clauses:search` |
| `risk` | `claim:read`, `documents:read`, `clauses:search` |
| `drafter` | `claim:read` |

On every call with an OBO token the API also checks the scope and the bound claim, refuses listing
claims, writing notes and minting tokens, records searches under the token's own run and agent, and
stops working as soon as the adjuster is suspended. Audit rows record the agent as `actor` and the
adjuster as `on_behalf_of`.
