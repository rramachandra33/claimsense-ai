# ClaimSense workflows

Each file follows one real example from the user's action (or the schedule, or a command) through
the console, the runner, the agents and the data API, and back: the function and the file at every
step, then the call chain at a glance. The architecture and the reasons behind it are in
[`../design.html`](../design.html); dated decisions in [`../../DECISIONS.md`](../../DECISIONS.md).

| Workflow | Example | Starts at |
|---|---|---|
| [Sign-in](sign-in.md) | alice signs in with Cognito; suspended frank is refused | `platform/web/src/app/login/actions.ts` |
| [Claims list and claim page](claims-and-access.md) | who sees which of the 20 claims, and why; alice tries carol's claim | `platform/web/src/app/claims/page.tsx` |
| [Run assessment](run-assessment.md) | alice runs CLM-2024-1800 on Claude: FLAG, $0.079 | `platform/web/src/app/claims/[id]/RunAssessment.tsx` |
| [Confirm or reject a draft](review-draft.md) | confirm; reject an agent-failure DENY; the $25,000 senior rule | `platform/web/src/app/claims/[id]/ReviewNote.tsx` |
| [Policy manual search](policy-manual-search.md) | a clause link, a word search, an agent's search, the quarantined chunk | `platform/web/src/app/clauses/page.tsx` |
| [Scheduled batch assessment](batch-assessment.md) | the 14 open claims; a rerun picks none | `batch/src/claimsense_batch/handler.py` |
| [Evaluation run](evaluation.md) | `make golden`; case EV-028 on a temporary copy | `agent/src/claimsense_agent/evaluate.py` |

Where the pieces run: locally everything is in Docker (`make stack`); on AWS the console, a private
data API, the runner and PostgreSQL are on EC2, the agents on AgentCore, the MCP server, the Claims
API for agents and the batch on Lambda, and sign-in on Cognito (`design.html` §2).
