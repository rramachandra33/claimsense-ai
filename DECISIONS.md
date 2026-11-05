# ClaimSense AI: decisions

Dated record of what was decided, why, and where it lives in the code. Newest first within each
section. The ten original open questions and their answers are in
`docs/ClaimSense-AI-Open-Questions-Answers.pdf` (26 Oct 2026); they are summarised at the end.

## Decision rules

### Precedence (open question 2) · decided 2026-11-04
When several outcomes are signalled, the note carries the first of **DENY, FLAG, ROUTE, APPROVE**.
No cover ends it; fraud review comes before any specialist or payment; a specialist comes before
payment. This matches the reasoning of the course's earlier evaluation cases.
Nothing is dropped: code adds to every note **"Also needs:"** (each signal for another outcome, with
its clause) and **"Pending documentation:"** (each documentation gap).
`PRECEDENCE`, `code_outcome`, `note_additions` in `agent/src/claimsense_agent/facts.py`.

### A documentation gap on its own · decided 2026-11-04
FLAG (an estimate pending OCR cannot support payment, CLS-DOC-009). When code found no fraud
indicator, the note says "Code found no fraud indicators: this FLAG is for the pending
documentation", so it is not read as a fraud referral.

### Draft outcome guard (EV-025) · decided 2026-11-04
DENY and ROUTE rest on facts code works out exactly, so a model draft follows code on them. Given
code's outcome, a draft may be: DENY → DENY; FLAG → FLAG; ROUTE → ROUTE or FLAG; APPROVE → APPROVE
or FLAG. Anything else is replaced by code's draft (`deterministic_fallback`). This also enforces the
precedence order on model drafts.
A **DENY code has no reason for becomes a FLAG** that keeps the agents' reason: they may have seen an
exclusion code cannot check (CLS-EXC-010), and an unchecked DENY never goes out.
`ALLOWED_DRAFT_OUTCOMES`, `unsupported_deny_flag` in `agent/src/claimsense_agent/pipeline.py`.

### VIN mismatch (EV-035) · decided 2026-11-04
A claim whose VIN differs from the policy's is a misrepresentation indicator under CLS-FRD-007:
FLAG. The note says "the claim's VIN (ending …) does not match the VIN on the policy" (last six
characters only). Code does the check: the risk agent's token cannot read the policy.

### Unmapped loss type (EV-039) · decided 2026-11-04
A loss type `LOSS_CATEGORY` does not map to collision or comprehensive gets no cover decision from
code: ROUTE, "an adjuster must decide which cover applies, if any", cited under CLS-COMP-002 with
both insuring clauses named. New loss types are added to the mapping, never guessed.

### Loss-location check (EV-001) · decided 2026-11-04
On by default: a FNOL and police report giving different loss locations is a CLS-FRD-007 fraud
indicator (FLAG). In the course data that is CLM-2024-1800, 1946, 2019 and 2092; 1800 is therefore a
FLAG. `CLAIMSENSE_LOCATION_CHECK=0` turns it off for data whose location fields are not comparable.

### EV-022 (loss on the policy's last day) · decided 2026-11-04
Expected APPROVE only. The period is inclusive (CLS-PER-006); a FLAG there is model inconsistency the
evaluation should keep showing.

### Agent failure · decided 2026-11-03
When an agent cannot finish (for example it runs out of turns), code writes an uncited DENY,
`decision_source: agent_failure`, saying "An adjuster must assess this claim". Refusals of access
(403) and API errors still write nothing. "For now": revisit once agent failures are rare.

### Risk agent search limit · decided 2026-11-03
The risk agent searches the manual at most 3 times (it looped to its 15-turn limit on CLM-2024-2092).

### Fraud threshold · provisional
Vendor fraud score 0.70 (the manual gives no number).

## People and review

### Drafts are confirmed or rejected by people · decided 2026-11-04
Every note is a draft (`draft_pending_confirmation`); nothing is paid or closed automatically. An
adjuster confirms or rejects it once; the review is stored beside the append-only note
(`claims_mgmt.note_reviews`) with who, when and why, and audited.
* Reviewers: adjusters and senior adjusters who may read the claim. Fraud investigators and
  total-loss appraisers review only; agents and service accounts never confirm (question 8).
* Above $25,000 net payable, only a senior adjuster confirms (CLS-PAY-012).
* A rejection needs a reason. **An agent-failure DENY needs a reason for either decision**, and any
  adjuster who may read the claim may review it.
`POST /api/v1/claims/{claim_id}/notes/{note_id}/review`.

### Assessing an already decided claim · decided 2026-11-04
Allowed, as a second opinion. The console asks "It is already approved. Rerun it?" first; the note
says "Second opinion: the claim was already Approved…", and the assessment records the claim's status
at run time (`claim_status_at_run`).

## Platform

### Where things run · decided 2026-11-03
* **AgentCore Runtime** runs the four agents (arm64 container, `GET /ping`, `POST /invocations`);
  the console's runner on EC2 forwards runs to it with SigV4.
* **Lambda** hosts the Claims API (in the VPC, reaching PostgreSQL on EC2) and the **MCP server with
  its self-hosted registry** (`/registry/v0/servers`). The MCP server moved to Lambda because
  AgentCore could not reach it on the EC2 instance.
* **EC2** (t3.small, a new instance, not the ClarityFi one) runs PostgreSQL, the console and the
  runner in Docker Compose.
* **Observability**: OpenTelemetry spans to CloudWatch (Transaction Search), metrics in namespace
  `ClaimSense`, three dashboards (experience, economics, quality) and two alarms. A **resolution** is
  a run that writes a note. Alarm emails (SNS): not now (2026-11-04).

### Secrets in Lambda environment variables · decided 2026-11-03
The JWT secret and database password are Lambda environment variables (encrypted at rest). Secrets
Manager from inside the VPC needs an interface endpoint (about $7 a month); revisit for production.

### Amazon Cognito sign-in (open question 9) · decided 2026-11-05
People sign in with a user name and password checked by Cognito (pool `claimsense-users`, app
client `claimsense-console`), on the console's own form: its server calls Cognito and keeps the
access token in the httpOnly cookie (Cognito's hosted page needs HTTPS return addresses, and the
EC2 console is plain HTTP). The data API checks the token's RS256 signature against the pool's
public keys, the issuer, the app client and `token_use=access`, and maps `username` to
`claimsense.users`; the Cognito group must equal the user's group there, and a suspended user is
refused whatever Cognito says.
* **Development sign-in off on EC2**, and a person's development token is refused wherever Cognito
  is configured. Locally it stays on. The batch account keeps its own token (not a person, not in
  the pool); agents keep OBO tokens, minted by our API (Cognito has no token exchange).
* **No MFA for now** (add for production); no self sign-up; administrator-only recovery.
* **8-hour access tokens**, the console's session. Sign-out clears the cookie but cannot revoke a
  token the API checks offline: a shorter token with refresh is the production fix.
* The Lambda API has no internet (VPC), so its deploy stores the pool's public keys in its
  environment; re-deploy after Cognito rotates them.
`api/src/claimsense_api/auth.py`, `platform/web/src/lib/cognito.ts`, `deploy/cognito/`.

### Development sign-in only on the EC2 private API · decided 2026-11-03
The public Lambda Function URL has development sign-in off (404). Sign-in stays on the API inside
the EC2 instance until Cognito replaces it; both share the token secret. (Since 2026-11-05: off on
EC2 too once Cognito is set up, see above.)

### Console cookie over plain HTTP · decided 2026-11-04
`CLAIMSENSE_COOKIE_SECURE=0` on EC2 while the console is plain HTTP (a Secure cookie would be
dropped). Turn it back on behind HTTPS.

## Batch assessment · decided 2026-11-04, built 2026-11-05
Every 4 hours (EventBridge Scheduler → Lambda `claimsense-batch` → AgentCore), assess open claims
(Pending Review, Under Investigation, Escalated) never assessed or whose documents changed since the
last assessment: a fingerprint of the claim's documents is stored on each assessment, so the
client's documents table needs no change. Runs as the `claimsense-batch` service account (reads open
claims only, cannot sign in or confirm); notes are drafts for the assigned adjuster, author
`claimsense-batch`. At most 25 claims a batch and $5 a day; no retries (the next batch picks up a
failed claim). The "skip documents changed in the last hour" idea was dropped: the document store has
no change times. `deploy/batch/README.md`.

## The original open questions (26 Oct 2026, summary)

1. Course fixtures are the core dataset. 2. Four outcomes; precedence decided above. 3. Claims
management, policy administration and the document store in PostgreSQL behind an MCP server; no
citation → DENY "no supporting clause found". 4. The only write is a cited draft, as an append-only
claim note, retried with the same idempotency key. 5. Subrogation out of scope. 6. The AutoSure
manual's rules as written; gaps defined here. 7. Our evaluation suite, rebuilt from the course claims.
8. Role table: alice, david adjusters (own claims, confirm up to $25,000); bob senior (all claims,
confirms above $25,000); carol fraud investigator and eve total-loss appraiser review only.
9. Amazon Cognito (built 2026-11-05, see Platform). 10. PostgreSQL.
