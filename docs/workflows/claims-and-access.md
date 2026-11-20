# Claims list and claim page — UI → backend workflow (who sees what)

## Example used

The same 20 course claims, seen by each user (computed by `can_read_claim` on the course data):

| User | Group | Sees | Why |
|---|---|---|---|
| alice | adjuster | 6 | assigned: 1800, 2092, 2165, 2384, 2749, 3041 |
| david | adjuster | 6 | assigned |
| bob | senior-adjuster | 20 | 3 assigned, 17 "senior adjuster reads all claims" |
| carol | fraud-investigator | 3 | assigned (1873, 2603, 2968); the only claims with a fraud score ≥ 0.70 (1873, 2603) are already hers |
| eve | total-loss-appraiser | 4 | assigned 1946, 3187; plus 2457 and 3114 from the total-loss queue (repair ≥ 75% of ACV) |
| claimsense-batch | batch-service | 14 | the open claims (Pending Review, Under Investigation, Escalated) |
| frank | adjuster, suspended | 0 | 403 on every request |

Then alice opens **CLM-2024-1800** (hers), and tries **CLM-2024-1873** (carol's) by typing its URL.

Source tests: `api/tests/test_access.py`, `api/tests/test_data_routes.py`.

**Important architectural note:** the console has **no access rules**. It sends the user's token,
and the API returns only what the rule allows. An unknown claim and a forbidden claim get the
**same 403** ("Claim … is not available to you."), so the API never confirms that a claim exists. The
real reason goes only into `claimsense.audit_log`.

---

## 1. User action in the browser

After sign-in the browser lands on `/claims` (the home page `/` redirects there).

| Step | Function | File |
|---|---|---|
| Home | `Home()` → `redirect("/claims")` | `platform/web/src/app/page.tsx` |
| Queue page (server component) | `ClaimsPage()`: `requireSession()`, then `apiGet("/api/v1/claims")` | `platform/web/src/app/claims/page.tsx` |
| Open a claim | link to `/claims/CLM-2024-1800` | `platform/web/src/app/claims/page.tsx` |

## 2. Frontend request

`apiGet(path)` runs on the console's server: it reads the session cookie and calls the data API with
`Authorization: Bearer <token>`, `cache: "no-store"`. A refusal comes back as `{ ok: false, status,
error }`, so the page shows the API's own message.

| Step | Function | File |
|---|---|---|
| Call the API | `apiGet<T>(path)` | `platform/web/src/lib/claimsense.ts` |
| API base URL | `CLAIMSENSE_API_URL` (on EC2: the private API container, `http://api:8000`) | `deploy/ec2/docker-compose.ec2.yml` |

## 3. API: the claims list

| Step | Function | File |
|---|---|---|
| Route | `list_claims()` — `GET /api/v1/claims` | `api/src/claimsense_api/main.py` |
| Who is calling | `require_user()` → `get_user()` (token, user row, group, active), rate limit | `main.py`, `auth.py`, `ratelimit.py` |
| Agents may not list | `check_agent(user, "claims:list", …)`: no agent has this scope, so an OBO token gets 403 | `api/src/claimsense_api/main.py` |
| Filter | every claim → `can_read_claim(user, claim)`; keep the allowed ones | `api/src/claimsense_api/access.py` |
| Audit | one row: `"6 of 20 claims visible"` | `api/src/claimsense_api/audit.py` |

The rule, in order (`can_read_claim`, returns `(allowed, reason)`):

```text
no group                         → no
batch-service                    → yes if the claim is open, else no
assigned_adjuster == user        → yes  "assigned"
senior-adjuster                  → yes  "senior adjuster reads all claims"
fraud-investigator, score ≥ 0.70 → yes  "fraud queue (vendor score >= 0.70)"
total-loss-appraiser, repair ≥ 0.75 × ACV → yes "total-loss queue (repair >= 75% of ACV)"
otherwise                        → no   "not entitled (assigned to carol)"
```

## 4. API: one claim

The claim page makes four calls; each one checks access again.

| Step | Function | File |
|---|---|---|
| Page | `ClaimPage()`: `apiGet` for `/claims/{id}`, `/claims/{id}/policy`, `/claims/{id}/documents`, `/claims/{id}/notes` | `platform/web/src/app/claims/[id]/page.tsx` |
| Every claim route | `load_claim_for(user, claim_id, action, scope)`: `check_agent` (scope, and an OBO token's own claim) → read the claim → unknown: audit "unknown claim", 403 → `can_read_claim` → audit allow/deny with the reason → 403 if denied | `api/src/claimsense_api/main.py` |
| Policy | `get_policy()`: read **through the claim**, so policy ids cannot be browsed; holder names are left out of the column list | `api/src/claimsense_api/main.py` |
| Documents | `list_documents()`: the inventory, no text | `api/src/claimsense_api/main.py` |
| One document | `get_document()`: finds the document's claim, then `can_read_claim` on that claim; text is null unless OCR is Completed | `api/src/claimsense_api/main.py` |
| Notes | `list_notes()`: notes with their assessment and review; agents may not read notes | `api/src/claimsense_api/main.py` |

**alice → CLM-2024-1800**: allowed, reason `assigned`. **alice → CLM-2024-1873**: denied, audit reason
`not entitled (assigned to carol)`; alice sees only "Claim CLM-2024-1873 is not available to you."
**bob → CLM-2024-1873**: allowed, reason `senior adjuster reads all claims`.

## 5. Rendering

| Step | Function | File |
|---|---|---|
| Queue table | status and fraud-score badges | `platform/web/src/app/claims/page.tsx`, `platform/web/src/components/badges.tsx` |
| Claim page | Claim, Policy, Documents panels; `RunAssessment`; `NotesList` (Confirm/Reject shown only to adjusters and senior adjusters) | `platform/web/src/app/claims/[id]/page.tsx` |
| Refusal | the API's message in place of the claim | `platform/web/src/app/claims/[id]/page.tsx` |

## Seeing it in the audit log

```sql
SELECT ts, user_id, actor, action, resource_id, decision, reason
  FROM claimsense.audit_log ORDER BY audit_id DESC LIMIT 10;
```

Each row has the user, the acting agent (`actor`, `human` for a person), the claim or document,
allow or deny, the reason and, for agent calls, the run.

## Call chain at a glance

```text
ClaimsPage → requireSession → apiGet("/api/v1/claims")
  → list_claims → require_user → get_user
               → check_agent("claims:list")          (agents: 403)
               → for each claim: can_read_claim       (access.py)
               → log_audit("6 of 20 claims visible")

ClaimPage → apiGet ×4 → get_claim / get_policy / list_documents / list_notes
  → require_user → load_claim_for → check_agent → can_read_claim → log_audit
  → 200, or 403 "not available to you" (unknown and forbidden alike)
```
