# Scheduled batch assessment — schedule → backend workflow

## Example used

The 20 course claims have **14 open** ones (Pending Review, Under Investigation, Escalated). A first
batch picks every open claim never assessed; a second batch right after picks **none**, because
nothing changed. If a new document arrives on, say, CLM-2024-2165, its fingerprint changes and the next
batch picks it again.

- Locally (mock agents, free): `claimsense-batch --runner http://localhost:8100` wrote 14 notes;
  run again, 0.
- On AWS (2026-11-05 preview): 13 candidates (CLM-2024-1873 had already been assessed), $0 spent
  today. The Lambda and the schedule are deployed; the schedule is **paused** and the first AWS batch
  (about $1) has not been run.

Source tests: `batch/tests/test_handler.py` (5 tests: limits, budget, time, failures),
`api/tests/test_batch.py` (the batch account and candidate selection).

**Important architectural note:** there is no person in this flow, so the batch acts as its own
**service account**, `claimsense-batch` (group `batch-service`). The API lets it read **open claims
only**; it cannot sign in, list other claims, or confirm anything. Its notes are drafts for the
claim's **assigned adjuster**, with author `claimsense-batch`, and go through the same pipeline and
checks as a run from the console.

---

## 1. The trigger

| Step | What | Where |
|---|---|---|
| Schedule | EventBridge Scheduler `claimsense-batch-every-4h`, `rate(4 hours)`, no retries | `deploy/batch/deploy.sh` |
| Target | Lambda `claimsense-batch` (Python, 15-minute timeout, 256 MB), role `claimsense-batch-lambda` | `deploy/batch/deploy.sh`, `deploy/batch/iam/` |
| Entry point | `handler(event, context)` | `batch/src/claimsense_batch/handler.py` |

Settings: `BATCH_MAX_CLAIMS` 25, `BATCH_DAILY_BUDGET_USD` 5, `BATCH_PARALLEL` 3, plus
`CLAIMS_API_URL`, `AGENTCORE_RUNTIME_ARN`, `CLAIMSENSE_JWT_SECRET`.

## 2. The batch account's token

| Step | Function | File |
|---|---|---|
| Sign | `batch_token()`: one hour, `sub: claimsense-batch`, group `batch-service`, HS256 with the shared secret | `batch/src/claimsense_batch/handler.py` |
| Accepted by the API | `get_user()`: development-issuer tokens are refused for people once Cognito is on, but **not** for the `batch-service` group | `api/src/claimsense_api/auth.py` |

## 3. Which claims

| Step | Function | File |
|---|---|---|
| Ask | `get_candidates(token, limit)` → `GET /api/v1/batch/candidates?limit=25` | `batch/src/claimsense_batch/handler.py` |
| Route | `batch_candidates()`: only the `batch-service` group, never an OBO token (403 otherwise) | `api/src/claimsense_api/main.py` |
| Select | `candidates(limit)`: open claims whose latest assessment is missing (**never assessed**, first) or has a different documents fingerprint (**documents changed**) | `api/src/claimsense_api/batch.py` |
| Fingerprint | `claimsense.documents_fingerprint(claim_id)`: md5 over each document's id, OCR status and text hash; stored on every assessment, so the client's documents table needs no change | `platform/db/schema.sql`, `migrations/2026-11-05_batch_assessment.sql` |
| Spend | `spent_today_usd()`: sum of the cost recorded on today's batch assessments (UTC) | `api/src/claimsense_api/batch.py` |

Answer: `{"claims": [{claim_id, assigned_adjuster, claim_status, reason}], "count", "needing_assessment", "spent_today_usd"}`.

## 4. Running them

| Step | Function | File |
|---|---|---|
| Loop | `run_batch(run_claim, answer, max_claims, budget, parallel, time_left_ms)`: rounds of up to 3 in parallel (`ThreadPoolExecutor`) | `batch/src/claimsense_batch/handler.py` |
| Budget | before each round: affordable = (budget − spent) ÷ $0.10 (`ESTIMATED_RUN_COST_USD`); 0 → stop "daily budget reached" | `batch/src/claimsense_batch/handler.py` |
| Time | less than 4 minutes left in the Lambda → stop "out of time" | `batch/src/claimsense_batch/handler.py` |
| One claim | `run_on_agentcore(token, claim_id)`: `invoke_agent_runtime` with `{"claim_id", "user_token": <batch token>}`, one attempt; an error becomes a failed result, and the batch goes on | `batch/src/claimsense_batch/handler.py` |
| On AgentCore | `invoke()` → `assess()` → `run_assessment()`: the same pipeline as [run-assessment.md](run-assessment.md); every claim read is checked with `can_read_claim` ("batch: open claim") | `agent/…/runner.py`, `pipeline.py`, `api/…/access.py` |
| The note | `write_note()` in the API: for the batch account, `on_behalf_of` = the claim's assigned adjuster, author `claimsense-batch`, assessment `trigger = 'batch'` | `api/src/claimsense_api/notes.py` |

A failed claim is not retried in the same batch: it is still a candidate, so the next batch picks it up.

## 5. Summary and metrics

| Step | Function | File |
|---|---|---|
| Summary | picked, runs, failures, not run, why it stopped, cost, spent today, one line per claim | `batch/src/claimsense_batch/handler.py` |
| Log | `print(json.dumps({"batch": summary}))` → CloudWatch Logs | `batch/src/claimsense_batch/handler.py` |
| Metrics | `publish(summary)`: `BatchClaimsPicked`, `BatchRuns`, `BatchFailures`, `BatchCostUsd` in namespace `ClaimSense` (a failure here never fails the batch); each run also publishes its own run metrics on AgentCore | `batch/src/claimsense_batch/handler.py` |

## 6. What the adjuster sees

On the claim page the note shows "by the scheduled batch" and is a draft like any other: the assigned
adjuster confirms or rejects it ([review-draft.md](review-draft.md)).

## Locally

`claimsense-batch --runner http://localhost:8100` (`main()` in `handler.py`) runs one batch through the
local runner's `/invocations` (the same contract as AgentCore), with the mock agents, for free.

## Call chain at a glance

```text
EventBridge Scheduler (every 4 h) → Lambda claimsense-batch handler
  → batch_token
  → get_candidates → GET /api/v1/batch/candidates → batch_candidates → candidates (fingerprints)
                                                                     → spent_today_usd
  → run_batch: rounds of 3, within 25 claims, $5/day, time left
      → run_on_agentcore → AgentCore /invocations → assess → run_assessment
          → … same pipeline … → write_note (on behalf of the assigned adjuster, author claimsense-batch)
  → print summary → publish (BatchClaimsPicked, BatchRuns, BatchFailures, BatchCostUsd)
```
