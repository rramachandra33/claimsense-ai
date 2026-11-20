# ClaimSense AI: engagement charter

Milestone 1, item 1 · pilot for a motor insurer · synthetic data only

## Why this engagement

Adjusters handle every claim by hand across three systems. One adjuster gathers the file, checks
coverage, assesses fraud, total loss and injury exposure, and writes the first decision. Decisions
vary between adjusters, the reasoning is not recorded, and fraud referral is triggered by a vendor
score rather than a reading of the file. The bottleneck is gathering the file: the same facts are
looked up in three places for every claim.

Adding rules to the existing rule table does not fix this. Coverage depends on the wording of a
policy clause, and fraud depends on whether the story is consistent across the documents.

## What the pilot delivers

A co-pilot that, for any claim, drafts a first decision (APPROVE, FLAG, ROUTE or DENY) in under a
minute, with its reasoning and the policy clauses it rests on. The adjuster stays the
decision-maker: code checks every draft, and an adjuster confirms or rejects it. Nothing is paid or
closed by the system.

The rules that can be written down (policy dates, cover, deductibles, the 75% total-loss and
$25,000 senior-approval thresholds, and the precedence DENY > FLAG > ROUTE > APPROVE) are applied
by code. The model reads the file, matches the policy wording and drafts the note.

## The three client systems and their integration points

All three are reached through one data API, which checks the user's entitlement before returning
anything, and an MCP server that exposes the API to the agents as tools.

| System | Holds | Integration point (data API) | Agent tool (MCP) | Direction |
|---|---|---|---|---|
| Claims management | claims, assigned adjuster, status, notes and note reviews | `GET /api/v1/claims`, `GET /api/v1/claims/{id}`; `POST /api/v1/claims/{id}/notes` (idempotent on `Idempotency-Key = run_id`); `POST …/notes/{note_id}/review` | `get_claim` | read; write of draft notes only by the runner, reviews only by adjusters |
| Policy administration | policies, coverages, deductibles, the policy manual's clauses | `GET /api/v1/claims/{id}/policy`, `GET /api/v1/clauses?q=`, `GET /api/v1/clauses/{id}` | `get_policy`, `search_clauses` | read only |
| Document store | FNOL, estimates, police and witness statements (OCR text) | `GET /api/v1/claims/{id}/documents`, `GET /api/v1/documents/{id}` | `list_documents`, `get_document` | read only |

Identity comes from Amazon Cognito (four groups: adjuster, senior adjuster, fraud investigator,
total-loss appraiser). Each agent calls the tools under its own five-minute on-behalf-of token for
one user, one claim and one run. Every call, allowed or refused, is written to the audit log.

## Scope

**In:** first drafts for claims already in the claims system; the adjuster's review in a console;
access control and audit; evaluation, monitoring, an incident drill and a runbook.

**Out:** claim intake (FNOL capture), settling or paying claims, final fraud findings (the system
flags indicators and recommends referral), acting on data mismatches, OCR, integration into the
client's existing UI, real policyholder data, high availability.

## How success is measured

Four quantified criteria (`SUCCESS-CRITERIA.md`): decision accuracy, pipeline latency, adjuster
confirmation rate and fraud routing accuracy. The contract's acceptance criteria are in the
statement of work, §3 (`Milestone-2/ClaimSense_SOW.pdf`).

## People

Who approves, who reviews the output, who uses it daily and who can block rollout:
`STAKEHOLDERS-RACI.md`.

## Constraints

* Synthetic data only, until the client's controls review passes.
* AWS us-east-1; Claude Haiku 4.5 and Sonnet 4.5 through Amazon Bedrock; no model trained on client
  data.
* Five weeks, discovery to handover; milestones and sign-off in SOW §5.
* The vendor works under a least-privilege IAM role, never with root credentials.

## First decisions

Recorded, dated, with the reason and the code they live in, in `DECISIONS.md` at the repository
root: the outcome precedence and the draft guard (code decides what the model may draft), who may
confirm a draft, where each part runs, Cognito sign-in with on-behalf-of agent tokens, and the
150-case evaluation suite. The open questions answered by the instructors on 26 Oct 2026 are
summarised at the end of that file.
