# Run assessment — UI → backend workflow

## Example used

**alice** (adjuster) opens her claim **CLM-2024-1800** (2021 Toyota Camry, parking lot collision on
2024-02-14, repair estimate $3,200, ACV $24,500, already **Approved** in the claims system) and clicks
**Run assessment**. Documents: FNOL form, witness statement, police report, repair estimate, damage
photos, all OCR Completed.

What Claude produced for this claim in the golden run of 2026-11-09 (case EV-001):

```text
outcome          FLAG                       decision_source  model
cited            CLS-FRD-007, CLS-COLL-001, CLS-DED-004
tokens           33,286 in / 1,702 out      cost $0.079       53.5 s
summary          Draft FLAG, pending adjuster confirmation. The loss is covered under collision
                 coverage (policy in force, collision coverage purchased, $500 deductible applies).
                 However, the FNOL and police report record different loss locations: FNOL states
                 [address]; police report states [address]. … Net payable if approved: $2,700.
                 Second opinion: the claim was already Approved in the claims system when this
                 assessment ran.
```

Source tests: `agent/tests/test_pipeline.py` (the whole run with mock agents against a real API and
MCP server), `agent/tests/test_bedrock.py`, `api/tests/test_obo.py`, `api/tests/test_notes.py`;
evaluation case EV-001.

**Important architectural note:** the agents never write anything and never see another claim. The
pipeline (code) checks access first, computes the facts, gives each agent its own five-minute token,
checks the draft, and writes the note itself with **alice's** token. On AWS the pipeline runs on
**AgentCore**; the runner on EC2 only forwards the request. Locally the runner runs it directly.

---

## 1. User action in the browser

| Step | Function | File |
|---|---|---|
| Button | `RunAssessment({ claimId, claimStatus })` → `RunButton` | `platform/web/src/app/claims/[id]/RunAssessment.tsx` |
| Already decided? | `isDecided("Approved")` is true, so the button first asks **"It is already approved. Rerun it?"**; **Rerun** continues | `platform/web/src/app/claims/[id]/RunAssessment.tsx` |
| Run | `run()` → server action `runAssessmentAction(claimId)`; a spinner counts seconds while it waits | `platform/web/src/app/claims/[id]/actions.ts` |

## 2. Frontend request

| Step | Function | File |
|---|---|---|
| Call the runner | `runAssessment(claimId)`: `POST {CLAIMSENSE_RUNNER_URL}/runs` `{"claim_id": "CLM-2024-1800"}` with alice's token as `Authorization` | `platform/web/src/lib/claimsense.ts` |

## 3. Runner → AgentCore

| Step | Function | File |
|---|---|---|
| Route | `create_run(body, authorization)` — `POST /runs`; no token → 401 | `agent/src/claimsense_agent/runner.py` |
| On AWS | `forward_to_agentcore(token, claim_id)`: boto3 `bedrock-agentcore` `invoke_agent_runtime` (SigV4 with the instance role), payload `{"claim_id", "user_token"}`, 300 s read timeout, **one attempt** (a retry could start a second run) | `agent/src/claimsense_agent/runner.py` |
| On AgentCore | the same image: `invoke(body)` — `POST /invocations` → `assess(user_token, claim_id)` | `agent/src/claimsense_agent/runner.py` |
| Locally | `create_run` → `assess(token, claim_id)` directly | `agent/src/claimsense_agent/runner.py` |
| Run | `assess()`: `ApiClient(token)`, `asyncio.run(run_assessment(client, claim_id, brain, tracer))`, then metrics | `agent/src/claimsense_agent/runner.py` |

`ApiClient` (`agent/src/claimsense_agent/api.py`) calls the Claims API Lambda on AWS
(`CLAIMSENSE_API_URL`), with alice's token.

## 4. `run_assessment()` — the pipeline (`agent/src/claimsense_agent/pipeline.py`)

A new `run_id` (UUID) ties together everything this run does: OBO tokens, clause searches, audit rows,
the assessment and the note.

### 4.1 Code facts (alice's token; the access check happens here first)

| Step | Function | File |
|---|---|---|
| Read the file | `client.claim_file(claim_id)`: `GET /claims/{id}`, `/policy`, `/documents` — each runs `load_claim_for` → `can_read_claim` ("assigned"). A 403 ends the run here: **nothing is written** | `agent/…/api.py`, `api/…/main.py` |
| Facts | `compute_facts(claim, policy, documents)`: in force 2024-02-14 ✓, loss category collision, collision cover ✓, deductible $500, net payable min(3200, 24500) − 500 = **$2,700**, ratio 0.13, VIN matches, estimate readable | `agent/src/claimsense_agent/facts.py` |
| Location check | `locations_match(FNOL text, police report text)` → **different** | `agent/src/claimsense_agent/facts.py` |
| Signals | `outcome_signals()` → `FLAG · CLS-FRD-007 · fraud indicators: FNOL and police report give different loss locations` | `agent/src/claimsense_agent/facts.py` |
| Gaps | `documentation_gaps()` → none | `agent/src/claimsense_agent/facts.py` |

### 4.2 Code retrieves the clauses behind its own rules

`rule_clauses()` → CLS-COLL-001, CLS-PER-006, CLS-DED-004, CLS-FRD-007; for each,
`client.retrieve_clause(clause, run_id)` → `GET /api/v1/clauses/{id}?run_id=…&agent=code`, which logs it
in `claimsense.retrieval_log` for this run. So the draft can always cite the rules code applied.

### 4.3 The four agents, in order

For each agent, `run_agent()`:

1. `client.obo_token(claim_id, agent, run_id)` → `POST /api/v1/obo/token` (`issue_obo_token()` in
   `api/…/main.py`): alice must be able to read the claim; `make_obo_token()` (`api/…/obo.py`) signs a
   five-minute token with `sub: alice`, `act: claimsense-agent-<agent>`, `claim_id`, `run_id` and the
   agent's scopes.
2. `open_tools(agent, token, run_id)` (`agent/…/tools.py`): `find_mcp_url()` asks the MCP registry
   (`/registry/v0/servers`) for `io.claimsense/claims`, then opens an MCP streamable-HTTP session with
   the OBO token as the `Authorization` header.
3. The agent function runs (`agents/bedrock.py`, or `agents/mock.py` for the mock brain):
   `run_model()` builds an OpenAI Agents SDK `Agent` with `LitellmModel` (Claude on Bedrock),
   temperature 0, 2,000 max tokens, its tools and a typed `output_type`, and runs it with at most
   15 turns. Token usage and cost are recorded.

| Agent | Model | Tools (MCP) | Output (typed, `schemas.py`) |
|---|---|---|---|
| reader | Haiku 4.5 | get_claim, list_documents, get_document | `ReaderOutput`: summary, documents read, documents unreadable (OCR pending), findings |
| coverage | Sonnet 4.5 | get_claim, get_policy, search_clauses | `CoverageOutput`: covered (yes / no / cannot tell), reasoning, cited clauses |
| risk | Haiku 4.5 | get_claim, list_documents, get_document, search_clauses (≤3) | `RiskOutput`: refer to SIU, indicators, cited clauses |
| drafter | Sonnet 4.5 | get_claim | `DraftOutput`: outcome, summary, cited clauses, deny reason; its prompt holds code's facts, signals and gaps, the three agents' outputs and the **allowed clause ids** |

Every tool call goes **agent → MCP server (Lambda) → Claims API (Lambda)** with the agent's OBO token.
The API checks the scope and that the token is bound to this claim (`check_agent()`), records every
clause search under the token's run, and audits each call with `actor = reader/coverage/…` and
`on_behalf_of = alice`.

After coverage and risk, `check_citations()` → `drop_unretrieved()` removes any clause they cite that
no search returned in this run, so the drafter is never offered it.

### 4.4 Code checks the draft (the guardrail)

| Check | Function | If it fails |
|---|---|---|
| An agent could not finish (model error, out of turns) | `AgentFailed` | `agent_failure_deny()`: uncited DENY "an adjuster must assess this claim" (`agent_failure`) |
| Every cited clause was retrieved this run; a note cites something unless it is a DENY with a reason; a DENY has a reason; APPROVE only when code found no signal or gap; the outcome is allowed given code's outcome | `check_draft()` | `fallback_draft()`: code's own draft (`deterministic_fallback`), citing the clauses behind its reasons; if none was retrieved, DENY "no supporting policy clause" |
| Every cited clause exists in the manual (quarantined counts as absent) | `unknown_clauses()` → `GET /clauses/{id}` | `made_up_citation_deny()`: DENY |
| DENY with no reason code can see | `is_unsupported_deny()` | `unsupported_deny_flag()`: a FLAG that keeps the agents' reason |

Allowed outcomes, given code's: DENY → DENY; FLAG → FLAG; ROUTE → ROUTE or FLAG; APPROVE → APPROVE
or FLAG. For CLM-2024-1800 code's outcome is FLAG and the draft is FLAG: **"draft passes every check"**.

Then code adds to the summary:

- `note_additions()`: "Also needs:" (signals for other outcomes) and "Pending documentation:" (none here);
- `second_opinion_line("Approved")`: "Second opinion: the claim was already Approved …";
- `redact()` (`agent/…/redact.py`): street addresses, phone numbers and emails removed. Here the two
  loss addresses became **[address]**.

### 4.5 Code writes the note

| Step | Function | File |
|---|---|---|
| Build the body | outcome, summary, cited clauses, deny reason, `decision_source`, code facts, every agent's output, models, token usage, `claim_status_at_run` | `agent/src/claimsense_agent/pipeline.py` |
| Send | `client.write_note(claim_id, note, idempotency_key=run_id)`: `POST /api/v1/claims/{id}/notes`; retries timeouts and 5xx with backoff and jitter, never 4xx | `agent/src/claimsense_agent/api.py` |
| API route | `create_note()`: agents (OBO) refused; `load_claim_for(alice)`; `Idempotency-Key` required | `api/src/claimsense_api/main.py` |
| Validate | `check_note()`: run id, outcome, summary ≤ 2,000, decision source; a note must cite unless it is a DENY with a reason | `api/src/claimsense_api/notes.py` |
| Same key seen? | `find_previous()` → same body: return the stored note (`Idempotent-Replay: true`); different body: 409 | `api/src/claimsense_api/notes.py` |
| Cited = retrieved | `check_citations_were_retrieved()` against `retrieval_log` for this run (a second check, in the API) | `api/src/claimsense_api/notes.py` |
| Save, one transaction | `write_note()`: `claimsense.assessments` (with the documents fingerprint), `claims_mgmt.claim_notes` (append-only, status `draft_pending_confirmation`), `claimsense.idempotency_keys` | `api/src/claimsense_api/notes.py` |
| Audit | `write_note · allow · note written` | `api/src/claimsense_api/audit.py` |

## 5. Response back to the browser

`run_assessment()` returns a `RunResult` (`agent/…/schemas.py`): `status` (`written`, `replayed` or
`failed`), outcome, decision source, cited clauses, problems, note id, tokens and cost. `assess()` adds
the brain and `duration_ms`, and publishes metrics (`run_metrics()` → CloudWatch namespace `ClaimSense`:
Runs, RunDurationMs, Resolutions, Fallbacks, AgentFailures, Decisions by outcome, tokens, RunCostUsd).

The runner returns it to the console; `runAssessmentAction` calls `revalidatePath("/claims/CLM-2024-1800")`.

## 6. Rendering

| Step | Function | File |
|---|---|---|
| Result line | outcome and source; for a failed run "Run failed, nothing was written" with the problems | `platform/web/src/app/claims/[id]/RunAssessment.tsx` |
| The new note | `NotesList` → `NoteCard`: outcome, summary, clause links (each opens the policy manual on that clause), "Second opinion" tag, decision source, Confirm/Reject | `platform/web/src/app/claims/[id]/NotesList.tsx` |

## Traces

Each step above is a span (`Tracer` in `agent/…/trace.py`): code facts, rule clauses, reader,
coverage, risk, drafter, check draft, write note. Locally `make agent CLAIM=CLM-2024-1800 AS=alice`
prints the trace in the terminal; on AgentCore the spans go to CloudWatch (Transaction Search) through
OpenTelemetry.

## Call chain at a glance

```text
RunAssessment (browser) → runAssessmentAction → runAssessment → POST runner /runs
  → create_run → forward_to_agentcore → AgentCore POST /invocations → invoke → assess
    → run_assessment
        code facts:    claim_file (GET claim, policy, documents; access check) → compute_facts
                       → locations_match → outcome_signals → documentation_gaps
        rule clauses:  rule_clauses → retrieve_clause ×4 (retrieval_log)
        agents ×4:     obo_token → open_tools (registry → MCP session) → run_model (Claude)
                         └ MCP tool → Claims API (check_agent, load_claim_for, audit)
                       check_citations → drop_unretrieved
        check draft:   check_draft → unknown_clauses → is_unsupported_deny
                       → note_additions → second_opinion_line → redact
        write note:    write_note (Idempotency-Key = run_id) → create_note → check_note
                       → check_citations_were_retrieved → assessments + claim_notes
    → RunResult → run_metrics → CloudWatch
  → revalidatePath → NotesList shows the draft
```
