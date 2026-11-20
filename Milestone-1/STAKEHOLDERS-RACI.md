# ClaimSense AI: stakeholder map and RACI

Milestone 1, item 2 · roles at the client (a motor insurer) and the vendor. The engagement uses
synthetic data, so people are named by role; the console identities used in the pilot are given
where a role signs in.

## The four roles the brief asks for

| Question | Who | Why |
|---|---|---|
| Who approves | **Client claims lead** | Signs off each milestone (SOW §5) and accepts the pilot against SOW §3 |
| Who reviews the co-pilot's output | **Senior adjuster** (`bob`) | Reads every claim; the only role that may confirm a draft above $25,000 net payable |
| Who uses it daily | **Adjusters** (`alice`, `david`) | Read their own assigned claims, run an assessment, confirm or reject the draft |
| Who can block rollout | **Compliance (controls review)** and **IT security** | Real policyholder data is not used until the controls review passes (SOW §9); IT security owns the AWS account and Cognito |

## Stakeholder map

| Stakeholder | Interest | Influence | What they need from the pilot |
|---|---|---|---|
| Client claims lead | High | High | Faster first decisions, consistent and recorded reasoning, an adjuster accountable for each outcome |
| Senior adjuster | High | Medium | Drafts that cite the policy wording; a hard stop on large payments without them |
| Adjusters | High | Low | A draft in minutes instead of gathering the file across three systems |
| Fraud investigator (`carol`) | Medium | Medium | Referrals based on a reading of the file, not only the vendor score; review only, never confirms |
| Total-loss appraiser (`eve`) | Medium | Low | Total-loss candidates (repair ≥ 75% of ACV) in a queue; review only, never confirms |
| Compliance (controls review) | Medium | High (veto) | No access beyond entitlement; every access and refusal audited; synthetic data until approved |
| IT security / AWS administrator | Medium | High (veto) | Least-privilege IAM, no root use by the vendor, known gaps listed (MFA, HTTP, secrets, row-level security) |
| Vendor engineer (forward deployed) | High | Medium | Access to the data and a named reviewer; builds, operates during the pilot, hands over |

## RACI

R = responsible (does it), A = accountable (one per row), C = consulted, I = informed.

| Activity | Claims lead | Senior adjuster | Adjusters | Fraud / total loss | Compliance | IT security | Vendor engineer |
|---|---|---|---|---|---|---|---|
| Agree scope, SOW and price | A | C | I | I | C | C | R |
| Set the expected outcome of evaluation cases | A | R | C | C | I | I | R |
| Approve the access rules (who reads which claim) | A | C | I | C | R | C | R |
| Build and test the agents | I | C | I | I | I | I | A/R |
| Review a draft and confirm or reject it | I | A (above $25,000) | A/R (own claims, up to $25,000) | C (their queues) | I | I | I |
| Controls review before real data | C | I | I | I | A/R | C | C |
| Provision the AWS account, IAM roles and Cognito | I | I | I | I | C | A/R | C |
| Deploy, monitor and run the incident drill | I | I | I | I | I | C | A/R |
| Add or remove a user (runbook procedure 1) | C | I | I | I | I | A | R |
| Accept the pilot (SOW §3) | A/R | C | C | C | C | C | I |

## How the roles are enforced

The review rights above are enforced in code, not by agreement: only adjusters and senior
adjusters may review; an adjuster only on their own claims; a draft above $25,000 needs a senior
adjuster; a fraud investigator or total-loss appraiser can read their queue but never confirm
(`api/src/claimsense_api/access.py`, `notes.py`; `data/identity/users.json`).
