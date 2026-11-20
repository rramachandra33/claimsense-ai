# ClaimSense AI: handover pack

Milestone 5, item 6 · 20 November 2026 · every engagement artefact in one index

ClaimSense drafts a first decision on a motor claim (APPROVE, FLAG, ROUTE or DENY) with its
reasoning and the policy clauses it rests on. Code applies the written rules and checks every
draft, and a licensed adjuster confirms or rejects it. This page is where a new owner or a grader
starts: what to open first, how to check the five acceptance criteria yourself, and where every
deliverable lives. Synthetic data only.

## Start here

| | |
|---|---|
| Console | **https://claimsenseai.rajur-dev.com** (AWS us-east-1; HTTPS with a Let's Encrypt certificate) |
| Sign in as an adjuster | `david`: sees only the claims assigned to that account; confirms drafts up to $25,000 |
| Sign in as a senior adjuster | `bob`: sees every claim; the only role that confirms above $25,000 |
| Passwords | given in the submission form |
| Read first | the observation document (`docs/ClaimSense-AI-Observation-Document.pdf`, 5 pages) |
| Operate it | `docs/RUNBOOK.md` |
| Run it on a laptop | `README.md`: `make stack` starts everything with one command; `TESTING_LOCALLY.md` |

## Check the acceptance criteria yourself

The five criteria every first-time user must be able to demonstrate (brief §6, SOW §3).

| Criterion | Try this in the console | Evidence in the repository |
|---|---|---|
| 1. A decision on any claim | As `bob`, open any claim and run an assessment: a draft with reasoning and cited clauses appears in about 20–35 s | Golden run 19 Nov: 148/150, then 150/150 (`docs/ClaimSense-AI-Golden-Run-2026-11-19.md`); screenshots S17–S19 |
| 2. Refusal on entitlement | As `david`, open `https://claimsenseai.rajur-dev.com/claims/CLM-2024-1800` (assigned to `alice`): no claim data, the same answer as an unknown claim; as `bob` the same claim opens | EV-130, the recorded two-user test, with both requests and responses (`evals/results/20261119-134237-bedrock.json`); S20; the refusal in the audit log (S14) |
| 3. Attribution in every response | In a note, "How this was reached" shows code's facts beside the model's judgment, and the note says whether the model or code decided | `decision_source` on every result (`model` or `deterministic_fallback`); S19 |
| 4. Reproducible evidence | — | CI runs the 150 cases on every commit and blocks the image push below 90% (`.github/workflows/ci.yml`, S15, S16); `make golden` reruns them on Claude |
| 5. Operability without the author | Follow `docs/RUNBOOK.md` | Incident drill: detected in 1 min 46 s, recovered in 3 min 12 s (`docs/INCIDENT-2026-11-19-drill.md`); dashboards and alarms S05–S09 |

## Deliverables by milestone

### Milestone 1: discovery and scoping (`Milestone-1/`)

| Item | Where |
|---|---|
| Engagement charter, the three systems and their integration points | `Milestone-1/ENGAGEMENT-CHARTER.md` |
| Stakeholder map and RACI | `Milestone-1/STAKEHOLDERS-RACI.md` |
| Four quantified success criteria, with results | `Milestone-1/SUCCESS-CRITERIA.md` |
| Dated decisions with reasons | `DECISIONS.md` |
| Initial evaluation cases | `Milestone-1/cases.json` (60 cases, 28 Oct) |
| Discovery notes | `docs/ClaimSense-AI-Project-Overview.pdf`, `docs/ClaimSense-AI-Open-Questions.pdf` and `-Answers.pdf`, `docs/ClaimSense-AI-Spec-vs-Assumptions.pdf`, `docs/ClaimSense-AI-Scope-Claim-Intake.pdf` |

### Milestone 2: statement of work, pricing and architecture

| Item | Where |
|---|---|
| Statement of work v1.0 | `Milestone-2/ClaimSense_SOW.pdf` |
| Pricing model with its assumptions | `Milestone-2/ClaimSense_Pricing.pdf` |
| Architecture, data flows and the code/model boundary | `docs/design.html` (§2 architecture, §3 components); `docs/ClaimSense-AI-Workflow-Diagram.pdf` |
| Risk register (five risks, and which ones happened) | `docs/ClaimSense-AI-Risk-Register.md` / `.pdf` |
| Typed contracts and idempotency | `api/README.md` (every route; `Idempotency-Key` on the one write), `agent/src/claimsense_agent/schemas.py` (typed agent outputs), `docs/ClaimSense-AI-OBO-Agent-Permissions.pdf` |
| Synthetic data shapes | `platform/db/schema.sql`, `docs/ClaimSense-AI-Schema-ER-Diagram.pdf`, `docs/ClaimSense-AI-Data-Generation-Design.pdf`, `data/` |
| Cloud account and created resources | `docs/ClaimSense-AI-AWS-Evidence-Screenshots.pdf` (21 annotated screenshots) |

### Milestone 3: production agents

| Item | Where |
|---|---|
| Four agents on the OpenAI Agents SDK with strict typed outputs | `agent/` (`agent/README.md`); models: Claude Haiku 4.5 and Sonnet 4.5 on Bedrock |
| Containers; the stack starts with one command | `docker-compose.yml`, `make stack` |
| Retrieval over the policy manual, citing clauses actually retrieved | `mcp_server/` (`search_clauses`); the draft check rejects any clause not retrieved in the run |
| CI where a failing gate blocks the image push | `.github/workflows/ci.yml`, `deploy/ci/README.md` |
| All four outcomes; model and fallback distinguishable | `decision_source` on every note; DECISIONS.md, "Decision rules" |

### Milestone 4: integration and access control

| Item | Where |
|---|---|
| Data access boundary deployed and callable | Lambda `claimsense-api` and `claimsense-mcp` (`deploy/lambda/`), S03 |
| Every route needs a valid token | `api/src/claimsense_api/main.py`; Cognito (`deploy/cognito/`), S04 |
| Access control in code, before any agent runs | `api/src/claimsense_api/access.py`; `docs/ClaimSense-AI-Users-and-Access-Rules.pdf` |
| Two-user test recorded on the same claim | EV-130 in `evals/results/20261119-134237-bedrock.json` |
| Audit record for every call, allowed or refused | `claimsense.audit_log`, S14 |

### Milestone 5: evaluation, observability, reliability and handover

| Item | Where |
|---|---|
| 150-case suite with the adversarial families | `evals/cases.json`, `evals/README.md`; reports `docs/ClaimSense-AI-Golden-Run-2026-11-19.md` and `-2026-11-09.md`; results in `evals/results/` |
| Dashboard (error rate, call volume, p95 latency) and alarms | *ClaimSense-Experience*, *-Quality*, *-Economics*; alarms *BadRuns* and *SlowRuns*, emailed through SNS (`deploy/observability/`), S05–S09 |
| Incident drill and one-page report | `docs/INCIDENT-2026-11-19-drill.md` |
| Runbook: add a user, roll back, escalate a flagged claim, update the policy corpus | `docs/RUNBOOK.md` |
| Client presentation and demonstration | the narrated recording (link in the submission form); the live console above |
| Handover pack | this page |

## Submission 2 contents

| Required | Where |
|---|---|
| Codebase at the final tag | this repository, tag `submission-2` |
| Deployed frontend URL | https://claimsenseai.rajur-dev.com |
| Observation document (six sections) | `docs/ClaimSense-AI-Observation-Document.md` / `.pdf` |
| Demonstration recording, under 10 minutes | link in the submission form (8 min 42 s) |
| CI run on the submitted commit | GitHub Actions, workflow `ci` on the tagged commit |
| Annotated AWS screenshots | `docs/ClaimSense-AI-AWS-Evidence-Screenshots.pdf`, `docs/screenshots/` |

## Running and changing it

| Task | Where |
|---|---|
| Deploy from a fresh AWS account | `DEPLOY_AND_TEST_ON_AWS.md`, then `deploy/<part>/README.md` for each part |
| Release a change | push to `main`: CI tests, runs the gate and pushes images tagged by commit; `TAG=<commit> deploy/agentcore/deploy.sh` deploys with a smoke test and rolls back on failure |
| Restart the EC2 services | `docker compose up -d --no-deps api mcp runner web` in `/opt/claimsense`. **Never** a plain `docker compose up`: it reruns the seed job, which deletes every note |
| Where to look when something breaks | `docs/RUNBOOK.md`, last section; the dashboards; `claimsense.audit_log` |
| Why it is built this way | `DECISIONS.md`; `docs/design.html` §4 |
| What it costs | about $0.07 per assessed claim; EC2 about $15 a month while running, the Elastic IP about $3.60 a month |

## Known gaps, accepted for the pilot

MFA is not enforced in Cognito; secrets are in the instance's `.env`
and the Lambda settings; the database has no row-level security; there is no automated database
backup; one instance in one region. Each is listed with its production fix in SOW §9 and the risk
register.

## After grading

1. Remove the port 80 and 443 inbound rules on `claimsense-sg` (or keep them while the console
   should stay reachable), and the DNS record `claimsenseai.rajur-dev.com` when the address is released.
2. Reset the test passwords: `RESET_PASSWORDS=1 AWS_PROFILE=claimsense deploy/cognito/setup.sh`.
3. Release the Elastic IP, or stop the instance and keep it for about $3.60 a month.
4. At the end of the engagement, follow SOW §12 (export, then delete every resource listed).
