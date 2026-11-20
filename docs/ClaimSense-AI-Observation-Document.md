# ClaimSense AI: observation document

Submission 2 · 19 November 2026 · commit `aa97590` (code as deployed: `96c07fd`)

ClaimSense is a claims-adjudication co-pilot for a motor insurer. Given a claim, four Claude agents
read the file, check cover, assess fraud risk and draft a first decision (APPROVE, FLAG, ROUTE or
DENY) with the policy clauses it rests on. Code owns identity, access, dates and money, checks
every draft, and writes it as a note that a licensed adjuster confirms or rejects. Synthetic data
only: the 20 course claims, their policies and documents, and the 12-clause policy manual.

This document records what was deployed, how it was evaluated and observed, how it behaves when
something breaks, what is handed over, and what we learned. Evidence is referenced by file; the
annotated AWS screenshots are in `docs/ClaimSense-AI-AWS-Evidence-Screenshots.pdf` (numbered S01–S21
below).

---

## 1. Deployment

**Where it runs (AWS us-east-1)**

| Piece | Service | Notes |
|---|---|---|
| Console (Next.js, :3100), data API (FastAPI), MCP server, runner, PostgreSQL 16 | EC2 t3.small `i-0e0137af99bf21cc7`, Docker Compose (S01) | Images from ECR; the instance role gives ECR and Bedrock access, so no AWS keys are on the box |
| The four agents | Amazon Bedrock AgentCore Runtime `claimsense_runner`, arm64 image (S02) | OpenAI Agents SDK through LiteLLM; Claude Haiku 4.5 (reader, risk) and Sonnet 4.5 (coverage, drafter) |
| Data API and MCP server used by the agents | Lambda `claimsense-api` (in the VPC, reaches PostgreSQL privately) and `claimsense-mcp` (S03) | Each agent calls them with its own on-behalf-of token |
| Sign-in | Amazon Cognito pool `claimsense-users`, four groups (S04) | RS256 access tokens checked by the API; the group must match the role in `claimsense.users` |
| Scheduled batch | EventBridge Scheduler → Lambda `claimsense-batch` → AgentCore | Built and deployed, **disabled by decision** (S13; DECISIONS.md 2026-11-19) |
| Images | ECR: `claimsense-api`, `-runner`, `-seed`, `-web` (S10–S11) | Pushed by CI only after every test and the evaluation gate pass; tagged by commit |
| CI | GitHub Actions, AWS access through OIDC (no stored keys) (S15–S16) | Tests, then the 150-case gate, then the image push |

**How it was deployed.** Each piece has one script that is safe to re-run: `deploy/ec2/deploy.sh`,
`deploy/lambda/deploy.sh`, `deploy/agentcore/deploy.sh`, `deploy/cognito/setup.sh`,
`deploy/observability/setup.sh`, `deploy/batch/deploy.sh`. IAM changes are made by the account
owner as root, from the policy files in each `deploy/*/iam/` folder; the deploy user
(`rramachandra33`) has only the rights those files grant. `DEPLOY_AND_TEST_ON_AWS.md` walks
through it from a fresh account.

**Running state at submission.** Everything runs build `96c07fd` (EC2 services and AgentCore). The
console is at **`http://34.235.178.85:3100`**, an Elastic IP, so the address stays the same when the
instance is stopped and started. Graders sign in as `david` (adjuster: only the claims assigned to
that account; confirms up to $25,000) and `bob` (senior adjuster: every claim; the only role that confirms
above $25,000); the passwords are given in the submission form. Between the two, a grader can
repeat the two-user test (EV-130): `david` is refused a claim that `bob` can open.

**Cost.** One assessment on Claude costs about $0.07 (27,800 input and 1,400 output tokens across
the four agents; S19 shows $0.0702). The 150-case evaluation on Claude cost $8.49. The fixed cost
is the EC2 instance (about $15 a month while running) and the Elastic IP (about $3.60 a month); Lambda, Cognito, ECR and CloudWatch are
within or close to the free tier at this volume.

**Problems found while deploying, and fixed** (all in the git history):
* Sign-out sent EC2 users to `localhost:3100`: inside the container the request URL is localhost.
  Fixed with a relative redirect (`c901588`).
* The data API on Lambda sits in the VPC with no internet route, so it cannot fetch Cognito's
  public keys. The deploy script stores them in the function's environment instead (re-run it if
  Cognito rotates its keys).
* Clause links on notes found nothing, because the word search cannot match an id. A clause id
  now opens that clause (`c33ef0e`).

---

## 2. Evaluation

**The suite.** 150 cases in `evals/cases.json`, built on the 20 course claims by
`scripts/build_eval_cases.py`, where each case carries its reasoning (`evals/README.md`).

| Family | Cases | What it tests |
|---|---:|---|
| baseline | 20 | each course claim as filed |
| variation | 52 | one change each: policy-period edges, cover, deductibles, the 75% total-loss and $25,000 senior thresholds, fraud score 0.69/0.70, prior claims, injury and police report, documents pending OCR, VIN mismatch, combined signals |
| attack | 9 | injected instructions, made-up / quarantined / unretrieved citations, personal details |
| prompt_injection | 15 | instructions hidden in estimates, captions, receipts, structured fields; fake JSON verdicts; base64, zero-width characters, Spanish; buried in long text |
| cross_record_leakage | 12 | documents asking for other claims' data; a misfiled FNOL from another claim; agent and user tokens on other claims' records |
| forced_auto_decision | 12 | `auto_finalize`, `skip_human_review`, claimed approvals and settlements; agents, the batch account and a fraud investigator trying to confirm; the $25,000 senior rule; a review cannot be overwritten |
| access | 16 | who may read which claim; the recorded two-user test (EV-130); missing, edited, unsigned, expired and wrong-group tokens; unknown claims answered like forbidden ones; encoded paths; `acting_as` ignored |
| token | 9 | what an agent's on-behalf-of token can and cannot do |
| holdout | 5 | claims never used as a variation base, never used for tuning |

Each case changes a temporary copy of a course claim (`CLM-9000-nnnn`) that is deleted afterwards;
the course claims are never modified. Cases that test the trust boundary call the data API directly
and keep every request and response (`agent/src/claimsense_agent/api_checks.py`).

**Results**

| Date | Brain | Cases | Passed | Cost | Notes |
|---|---|---:|---:|---:|---|
| 28 Oct | Claude | 60 | 57 | — | first full run; the decisions on precedence, VIN mismatch and unmapped loss types followed (DECISIONS.md, 4 Nov) |
| 9 Nov | Claude | 60 | 56 → 60 | $4.25 | four failures from evaluation copies whose documents still named the original claim; fixed in the harness (`docs/ClaimSense-AI-Golden-Run-2026-11-09.md`) |
| 19 Nov | Claude | 150 | **148** | $8.49 | two case-design issues (below); after the fix the four affected cases passed 4/4 on Claude ($0.28) |
| every commit | mock | 150 | 150 | $0 | the CI gate (S16): below 90% the build fails and no image is pushed |

The two failures on 19 November were faults in the cases, not in the system. EV-078 changed the
claim record to one prior claim but left the FNOL saying none; Claude flagged the discrepancy,
correctly. EV-079 expected APPROVE on a claim whose police report is still pending OCR; Claude
flagged it before payment, which the draft rules allow. The first case now updates the FNOL too;
the second now passes on APPROVE or FLAG as long as it is not a fraud referral.

**Every adversarial family held on Claude**: no injection changed an outcome or got a made-up clause
cited, no other claim's data reached an agent or a note (including the misfiled FNOL's policyholder
name), and no draft was confirmed or closed without an adjuster.

**What the gate does not cover.** The gate runs the mock brain: free, fast and repeatable, but it
never calls Bedrock. The incident drill (section 4) showed the consequence: a broken model id
passed the gate. The Claude run is manual (`make golden`, about $10 and 40 minutes).

---

## 3. Observability

**Metrics** (namespace `ClaimSense`, sent by the runner after each run on AgentCore and by CI):
`Runs`, `RunDurationMs`, `Failures`, `Resolutions` (runs that wrote a note), `Fallbacks` (code's
decision replaced the draft), `AgentFailures`, `InputTokens`, `OutputTokens`, `RunCostUsd`,
`Decisions` by outcome, and `EvalPassRate` from CI.

**Dashboards**
* *ClaimSense-Experience* (S07): run duration p50/p95, runs and failures (call volume and error
  rate), the Lambda functions' p95 duration, errors and throttles.
* *ClaimSense-Quality* (S08): the evaluation pass rate, live fallback / agent-failure / failure
  rates, decisions by outcome.
* *ClaimSense-Economics* (S09): model cost, resolutions and cost per resolution, tokens per hour.

**Alarms** (S05–S06): `ClaimSense-BadRuns` (more than 25% of runs in an hour failed, fell back or
had an agent failure) and `ClaimSense-SlowRuns` (run time over 2 minutes in 3 data points within
15 minutes).
BadRuns fired in the drill 1 min 46 s after the bad build went live.

**Logs and traces.** The Lambda functions log one line per request with its duration and X-Ray trace
id (S12). The runner exports its spans through OpenTelemetry, and the same trace id appears in the
AgentCore and Lambda records for one run. AgentCore Observability's trace views stay empty: they need
CloudWatch Transaction Search, which is not switched on (an extra cost).

**Audit.** `claimsense.audit_log` records every call to the data API, allowed or refused, with the
calling user, the acting agent, the action, the resource and the reason (S14). At submission:
1,028 allowed and 14 refused rows. Refusals tell the caller nothing; the reason is in the audit
log only.

**Per run, in the console** (S19): code's facts beside each agent's typed output, the clauses each
search returned, and tokens and cost per agent.

---

## 4. Platform reliability

**Designed in**
* *A failure never leaves a claim without a note.* An agent that cannot finish leads to a DENY
  written by code (`agent_failure`), which an adjuster must assess with a reason. A draft that fails
  code's checks is replaced by code's own decision (`deterministic_fallback`), and the note says so.
* *Writes are idempotent.* Code writes the note with `Idempotency-Key = run_id` and retries timeouts
  and server errors with exponential backoff and jitter; a retry returns the stored note, never a
  second one.
* *Rate limit:* 300 requests a minute per user on the deployed API; over it, a 429 before any data is
  read.
* *Rollback is one command:* every CI build is tagged with its commit (S11).
* *Smoke test on every agent deploy* (added after the drill): one dry run, no note written; if it
  fails, the previous image goes back automatically. Checked on AWS in both directions.

**Incident drill, 19 November** (`docs/INCIDENT-2026-11-19-drill.md`). A one-character change to
the Sonnet model id passed CI and was deployed to AgentCore. All four runs ended in agent-failure
DENY drafts; nothing wrong reached a claim.

| Bad build live | Alarm | Rollback done | Recovery verified | **Time to verified recovery** |
|---|---|---|---|---|
| 14:22:43 UTC | 14:24:29 (1 min 46 s) | 14:24:52 (16 s) | 14:25:55 | **3 min 12 s** |

**Known gaps** (all recorded, none hidden): one instance, one region, no high availability; no
automated database backup (a full redeploy reloads the course data and loses notes); the console is
plain HTTP, MFA is off in Cognito; secrets live in the instance's `.env` and the Lambda settings,
not Secrets Manager; the database has no row-level security (entitlement is enforced in the data
API).

---

## 5. Handover

| Need | Where |
|---|---|
| Run it locally | `README.md` (`make stack` starts everything with one command), `TESTING_LOCALLY.md` |
| Deploy it | `DEPLOY_AND_TEST_ON_AWS.md`, `deploy/*/README.md` |
| Operate it | `docs/RUNBOOK.md`: add a user, roll back a deployment, escalate a flagged claim manually, update the policy corpus |
| Understand it | `docs/design.html` (architecture, the code/model boundary, decisions), `DECISIONS.md` (every decision, dated, with the code it lives in), `docs/ClaimSense-AI-Risk-Register.md` (five risks, and which ones happened) |
| Trust it | `evals/README.md` and the golden-run reports, the incident report, the screenshot set, the audit log |
| Scope and price | `Milestone-2/` (statement of work and pricing), `Milestone-1/` (charter material, stakeholders, success criteria) |
| See it | the narrated demonstration recording (8 min 42 s) |

The runbook's rollback procedure was exercised in the drill. Its other three procedures were
checked against the code and scripts but not yet performed by a first-time operator.

---

## 6. Observations

1. **A mock-only gate cannot catch model configuration.** The drill's regression passed 150/150 in
   CI. Detection then depended on traffic reaching the alarm. The smoke test on every agent deploy
   closes most of the gap; running the Claude evaluation on changes to the agents would close the rest.
2. **Evaluation cases must keep a file consistent.** Three times, Claude "failed" a case because the
   case had changed one field and left documents saying something else (copies naming the original
   claim; an FNOL with the old prior-claims count). Claude was right each time. Every change now
   updates the documents that state the same fact.
3. **The model is stricter than the rules, and that is allowed.** Claude flags a claim before payment
   when a police report is still pending OCR, which no written rule requires. The draft rules let a
   draft go to FLAG where code says APPROVE or ROUTE, never the other way, so this costs reviewer time,
   not correctness.
4. **Access control in code held.** No evaluation case, on the mock or on Claude, read a claim it was
   not entitled to; agents never left their claim or their scopes; refusals carried no data, and each
   one is in the audit log with its reason.
5. **Observability exists; someone is now told.** Found during this review: the alarms had no
   actions and the log groups kept logs forever. Fixed on 19 Nov 2026 (`deploy/observability/setup.sh`):
   both alarms notify the SNS topic `claimsense-alarms` (email) on ALARM and on OK, and the API, MCP
   and AgentCore log groups keep 90 days. Still open: the alarm needs runs to fire, and an
   agent-failure alarm on a 5-minute window (incident action 4) is not built yet.
6. **Reachability for grading.** Until 20 Nov the console was served on port 3100 to one IP address,
   and the instance's public address changed on every start. Fixed for grading: an Elastic IP
   (`34.235.178.85`) and an inbound rule opening port 3100 to any address; SSH stays limited to one
   address. Graders use two existing course identities, `david` and `bob`, because a new account
   would own no claims (access follows the claim's assigned adjuster). Anyone with the URL reaches
   the sign-in page, so after grading the rule goes back to one address, the passwords are reset
   (`RESET_PASSWORDS=1 deploy/cognito/setup.sh`) and the Elastic IP is released. The HTTP-only
   console without MFA is acceptable for synthetic data and a capstone, not for production.
7. **Cost is small and predictable.** About $0.07 a claim on Claude; Sonnet for coverage and the draft,
   Haiku for reading and risk. The model choice per agent, not the platform, sets the cost.
