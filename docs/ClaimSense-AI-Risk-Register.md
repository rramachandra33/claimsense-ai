# ClaimSense AI: risk register

Milestone 2, item 4 · updated 19 November 2026 for Submission 2

Five risks, each with its likelihood, impact, mitigation and owner. The last part of each entry,
**Did it happen**, records what the evaluation runs, the deployment and the incident drill showed,
with the evidence. Related documents: `DECISIONS.md`, the statement of work (§9 security, §11
assumptions), `docs/INCIDENT-2026-11-19-drill.md` and the observation document.

**Scales.** *Likelihood*: Low (not expected during the pilot), Medium (could happen during the
pilot), High (expected without a control). *Impact*: Low (an inconvenience, no effect on a claim or
a person), Medium (claims are delayed or reviewers lose time), High (a wrong outcome on a claim,
claim data reaching someone who should not see it, or the service down). *Residual* is the rating
with the mitigation in place.

## Summary

| # | Risk | Likelihood | Impact | Residual | Did it happen |
|---|---|---|---|---|---|
| R1 | The model drafts a wrong or ungrounded decision | High | High | Low | Yes, caught by code every time |
| R2 | Claim data reaches a user or agent not entitled to it | Medium | High | Low | Attempted in tests; refused every time |
| R3 | A faulty release reaches the live service | Medium | High | Medium | Yes, in the drill; recovered in 3 min 12 s |
| R4 | The model or platform is unavailable | Medium | Medium | Medium | Yes, in the drill and once in deployment |
| R5 | The evaluation evidence misleads | Medium | High | Medium | Yes, in both directions |

## R1. The model drafts a wrong or ungrounded decision

**Risk.** An agent drafts the wrong outcome, cites a clause that does not exist or was never
retrieved, or follows instructions planted in a document, estimate or policy passage.

**Likelihood** High: language models do this without a control. **Impact** High: a wrong denial or
a payment that should not be made.

**Mitigation**

* Code, not the model, applies the rules that can be written down (policy dates, cover, deductibles,
  the 75% total-loss and $25,000 thresholds) and their precedence, DENY > FLAG > ROUTE > APPROVE.
* Code checks every draft before a note is written: the outcome must be one the rules allow
  (`ALLOWED_DRAFT_OUTCOMES`; the model may only move towards more caution), and every cited clause
  must be one the search returned in this run. A draft that fails is replaced by code's own decision
  (`deterministic_fallback`), and the note says so.
* Policy passages that contain instructions are quarantined and never reach the agents.
* An adjuster confirms or rejects every draft; above $25,000 net payable only a senior adjuster may
  confirm. Nothing is paid or closed by the system.

**Owner** engineering (checks), claims operations (review). **Residual** Low for claims (a person
decides), Medium for reviewer time.

**Did it happen.** Yes, and it was caught each time. In the 9 November Claude run, code replaced
Claude's draft on 9 of 60 cases: 4 cases that plant a bad draft (a clause that does not exist, the
quarantined clause, a clause never retrieved, an approval of a lapsed policy) and 5 where Claude
drafted ROUTE where the rules give FLAG (`docs/ClaimSense-AI-Golden-Run-2026-11-09.md`). In the
19 November run, no injection in the 24 attack and prompt-injection cases changed an outcome or got a
made-up clause cited. Watched on the *ClaimSense-Quality* dashboard (`Fallbacks`).

## R2. Claim data reaches a user or agent not entitled to it

**Risk.** A user reads a claim that is not theirs, or an agent working on one claim reads another
claim's documents, policy or notes and carries that data into a draft.

**Likelihood** Medium: a missed check on one route is enough. **Impact** High: personal data
exposed, a regulatory matter for an insurer.

**Mitigation**

* Entitlement is enforced in the data API, in code, before any agent runs and on every route; it is
  never a model instruction.
* Each agent acts under its own on-behalf-of token: five minutes, one user, one claim, one run, and
  only the scopes its role needs. Agents cannot write notes or mint tokens.
* A refusal looks the same as "not found", so it tells the caller nothing; the reason goes to the
  audit log, which records every call with user, agent, action and resource.

**Owner** engineering. **Residual** Low. The database has no row-level security, so a bug in the
data API is not caught by a second layer (SOW §9, known gaps).

**Did it happen.** Attempted, and refused every time. The 16 access, 12 cross-record-leakage and 9
token cases passed on the mock and on Claude, including the recorded two-user test (EV-130) and a
misfiled FNOL whose other policyholder's name did not reach the note. At submission the audit log
held 1,028 allowed and 14 refused calls (screenshot S14).

## R3. A faulty release reaches the live service

**Risk.** A change that breaks the live system (code, configuration or a model id) passes CI and is
deployed.

**Likelihood** Medium. **Impact** High: every assessment fails while it is live.

**Mitigation**

* CI runs the tests and the 150-case evaluation gate; below 90% the build fails and no image is
  pushed.
* Images are tagged by commit, so a rollback is one command (runbook, procedure 2).
* Added after the drill: every AgentCore deploy runs a smoke test (a dry run on one claim, no note
  written) and puts the previous image back if it fails (`deploy/agentcore/deploy.sh`, `96c07fd`).

**Owner** engineering. **Residual** Medium until the two open drill actions are done: check the model
ids against Bedrock before deploying, and run the Claude evaluation on changes to the agents.

**Did it happen.** Yes, in the incident drill on 19 November. A one-character change to the Sonnet
model id passed the gate 150/150, because the gate runs the mock brain, which never calls Bedrock.
All four runs on the bad build failed; the alarm fired after 1 min 46 s; the rollback took 16 s;
recovery was verified 3 min 12 s after the bad build went live. No wrong decision reached a claim.

## R4. The model or platform is unavailable

**Risk.** Bedrock returns errors or throttles, a call times out, or a dependency the system needs
(Cognito keys, the database) cannot be reached.

**Likelihood** Medium. **Impact** Medium: claims wait for a draft; no wrong outcome, because
nothing is decided without a person.

**Mitigation**

* An agent that cannot finish leads to a DENY written by code (`agent_failure`). The adjuster must
  give a reason to confirm or reject it, so it cannot be waved through.
* Note writes are idempotent (`Idempotency-Key = run_id`) and retried with exponential backoff and
  jitter; a retry returns the stored note, never a second one.
* A rate limit of 300 requests a minute per user protects the API.
* Two alarms (bad-run rate, slow runs) email the operator on ALARM and on OK (SNS topic
  `claimsense-alarms`, since 19 November).

**Owner** engineering, operations. **Residual** Medium: one instance in one region, no high
availability (SOW §11).

**Did it happen.** Yes. In the drill the model call failed on every run; the system wrote four
agent-failure drafts, did not crash, and the drafts were rejected by a senior adjuster with the reason
"incident drill". During deployment, the data API on Lambda could not reach Cognito's public keys
(no internet route from the VPC); the deploy script now stores the keys in the function's settings.

## R5. The evaluation evidence misleads

**Risk.** The suite passes while the live system is wrong, or fails because a case is wrong; or the
system is tuned to the cases and does worse on claims it has not seen.

**Likelihood** Medium. **Impact** High: acceptance is decided on this evidence.

**Mitigation**

* Each case states its reasoning and expectation (`evals/README.md`); a failure is investigated
  before anything is tuned, and the decision is recorded.
* A holdout family of five claims is never used as a variation base or for tuning.
* Besides the mock gate on every commit, the full suite is run on Claude (`make golden`) and the
  results are kept as dated reports.

**Owner** engineering, with the client's claims lead for the expected outcomes. **Residual** Medium:
the Claude run is manual, about $10 and 40 minutes.

**Did it happen.** Yes, in both directions. Three times a case was wrong, not the system: on
9 November four evaluation copies still named the original claim in their documents; on 19 November
EV-078 left the FNOL contradicting the claim record, and EV-079 expected APPROVE where Claude
correctly flagged a pending police report. And the mock gate passed a build that could not call the
model (R3).

## Also watched

* **Nobody is told when something breaks.** It happened: until 19 November the alarms had no
  actions and the logs never expired. Fixed the same day (SNS email, 90-day retention).
* **Cost overrun.** About $0.07 per claim on Claude; the 150-case run cost $8.49. Watched on the
  *ClaimSense-Economics* dashboard; an AWS Budgets alert on the account is recommended.
* **Loss of notes.** There is no automated database backup, and re-running the seed job reloads the
  course data and deletes notes. The runbook warns against it; a backup is needed before production.
* **Security gaps accepted for the pilot** (SOW §9): MFA off in Cognito, secrets in the instance's
  `.env` and the Lambda settings, no row-level security. Synthetic data only. The fourth gap in the
  SOW, the plain-HTTP console, was closed on 20 November: HTTPS through Caddy, Secure cookie.
