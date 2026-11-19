# Run and test ClaimSense locally, from scratch

Everything runs on a Mac with no AWS account (the mock agents), or with Claude on Amazon Bedrock if
you have the `claimsense` AWS profile. The AWS deployment has its own guide: `DEPLOY_AND_TEST_ON_AWS.md`.

What runs: PostgreSQL (Docker, port **5433**, so a PostgreSQL already on 5432 is untouched), the data
API (8000), the MCP server and its registry (8200), the runner that runs the four agents (8100) and
the console (3100).

## 1. Prerequisites (once)

| Tool | Check | Notes |
|---|---|---|
| Docker Desktop | `docker --version` | must be running |
| Node.js 22 | `node -v` | the console |
| Python 3.12+ and uv | `python3 -V`, `uv --version` | https://docs.astral.sh/uv/ |
| make, git, curl | | come with the Xcode command-line tools |
| AWS CLI v2 (optional) | `aws --version` | only for Claude (step 5) |

```bash
git clone https://github.com/rramachandra33/claimsense-ai.git ~/raju/CLAIMSENSE-AI   # private repo
cd ~/raju/CLAIMSENSE-AI
make doctor          # lists anything missing
```

## 2. Start

**Option A: the whole stack in Docker (recommended for testing)**

```bash
make stack                    # db, seed, api :8000, mcp :8200, runner :8100, console :3100 (first build: a few minutes)
make stack-logs               # follow the logs; make stack-down to stop
```

The first `make stack` writes `.env` with a random token secret. Every start reloads the course
data (20 claims), which removes earlier notes and reviews. After a new secret, a console sign-in
from before shows "Missing, expired or invalid token": sign out and in again.

**Option B: each service in its own terminal (faster when changing code)**

```bash
make up                                                                     # terminal 1: database + course data
export CLAIMSENSE_JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
CLAIMSENSE_DEV_LOGIN=1 make api                                             # terminal 1: API :8000
make mcp                                                                    # terminal 2: MCP :8200
make runner                                                                 # terminal 3: runner :8100
make web                                                                    # terminal 4: console :3100
```

Use the same `CLAIMSENSE_JWT_SECRET` in every terminal that needs one (the API, `make token`, the
batch command). `make up` and `make stack` share the container name: starting one stops the other.

## 3. Test every feature in the console (http://localhost:3100)

Sign in by typing a user id (the development sign-in, on by default locally; on AWS people sign in
with Amazon Cognito, and you can use Cognito locally too, see §3.6).

### 3.1 Access by role

| Sign in as | Expect |
|---|---|
| `alice` (adjuster) | 6 claims; `/claims/CLM-2024-1873` shows "Not available" |
| `david` (adjuster) | 6 claims |
| `bob` (senior adjuster) | all 20 claims |
| `carol` (fraud investigator) | 3 claims; no Confirm/Reject buttons on drafts |
| `eve` (total-loss appraiser) | 4 claims; no Confirm/Reject buttons |
| `frank` | refused (suspended) |
| `claimsense-batch` | refused (a service account cannot sign in) |

The **Policy manual** page never shows `CLS-ADM-013` (an injected clause), whatever you search.

### 3.2 Run assessment and the decision rules (mock agents, about 1 s each)

| Claim, as | Expect |
|---|---|
| CLM-2024-3041, alice | first a question "It is already approved. Rerun it?" (the claim is Approved): **Cancel** runs nothing; **Rerun** shows a spinner and a seconds counter, then **APPROVE** citing CLS-COLL-001, CLS-PER-006, CLS-DED-004, and the label "second opinion: claim was Approved" |
| CLM-2024-2165, alice | no question (Pending Review): a draft straight away |
| CLM-2024-1800, alice | **FLAG**: the FNOL and police report give different loss locations (CLS-FRD-007) |
| CLM-2024-2822, david | **DENY**: the loss is 3 days after the policy ended (CLS-PER-006) |
| CLM-2024-1873, bob | **FLAG** (fraud indicators), and the note ends with "Also needs: ROUTE: net payable 30200 > 25000, senior adjuster (CLS-PAY-012)" and "Pending documentation: …" (precedence DENY > FLAG > ROUTE > APPROVE) |
| CLM-2024-3114, bob | **DENY** (liability-only policy), with "Also needs" for the total-loss ROUTE |

Every note is a **draft pending confirmation**. "How this was reached" shows the code facts, the
signals, each agent's output and, on Claude, tokens and cost per agent.

### 3.3 Confirm or reject a draft

On a draft, as alice or david (or bob):

1. **Reject** with an empty reason: refused, "Give a reason."
2. **Reject** with a reason: the note shows **rejected**, "Rejected by alice · time · reason".
3. **Confirm** another draft: **confirmed**, "Confirmed by …".
4. A reviewed draft has no buttons any more (one review per draft).

The $25,000 rule (only a senior adjuster confirms above $25,000 net payable) and the
agent-failure rule (a reason is required to confirm) are covered by `make api-test`: in the course
data no adjuster's own claim is above $25,000.

### 3.4 The batch assessment (free, mock agents)

The scheduled batch runs on AWS; locally the same code runs through the local runner:

```bash
export $(grep ^CLAIMSENSE_JWT_SECRET .env)     # Option A; with Option B, use your exported secret
cd batch
CLAIMS_API_URL=http://localhost:8000 uv run claimsense-batch --runner http://localhost:8100
```

Expect "14 open claims need an assessment" (13 if you already ran one of them), one line per claim
(all `written`), and `"failures": 0`. Run it again: **0** claims (nothing changed). The notes show
"for <assigned adjuster> · by the scheduled batch". To see change detection, change a document and
run the batch again: that claim is picked with "documents changed since the last assessment":

```bash
docker exec claimsense-db psql -U claimsense -d claimsense -c \
  "UPDATE doc_store.documents SET ocr_text = ocr_text || ' (amended)' WHERE document_id = 'DOC-00010';"
```

(`make stack` or `make up` reloads the course data afterwards.)

### 3.5 Personal details and bad drafts

```bash
cd agent && uv run claimsense-agent run --claim CLM-2024-3041 --user alice --demo-bad-draft
# a draft citing a made-up clause CLS-XXX-999 → DENY, decided by code (deterministic_fallback)
```

Addresses in a note show as `[address]`.

### 3.6 Amazon Cognito sign-in (optional; needs the pool from `deploy/cognito/setup.sh`)

Locally the console uses Cognito when both ids are set; the development sign-in stays on in the API.
Create the pool once without touching EC2, then put the two printed lines in `.env`:

```bash
SKIP_EC2=1 AWS_PROFILE=claimsense deploy/cognito/setup.sh     # prints COGNITO_POOL_ID and COGNITO_CLIENT_ID
# add both lines to .env (Option A), or export CLAIMSENSE_COGNITO_POOL_ID / CLAIMSENSE_COGNITO_CLIENT_ID
# in the API and console terminals (Option B)
make stack                                                   # Option A picks them up
```

Passwords: `~/.claimsense/cognito-test-users.txt`. Expect:

| Sign in as | Expect |
|---|---|
| `alice` with her password | 6 claims; Run assessment works (the runner passes her Cognito token on) |
| `alice` with a wrong password | "Wrong user name or password." |
| `frank` with his password | "Your account may not use ClaimSense." (Cognito accepts him; ClaimSense has him suspended) |
| `claimsense-batch` | "Wrong user name or password." (the batch account is not in the pool) |

The 17 tests in `api/tests/test_cognito.py` cover the token rules without a pool (they play
Cognito with their own key): wrong key, other pool, other app client, ID token, expired, group
mismatch, an HS256 token claiming to be Cognito's, and development tokens refused once Cognito is on.
Remove the two lines from `.env` to go back to the development sign-in.

## 4. Automated tests and the evaluation (need only the database: `make up` or `make stack`)

```bash
make api-test     # 105 tests: access, Cognito tokens, notes, reviews, the batch account, rate limit, Lambda handler
make mcp-test     # 9 tests: the MCP server and registry over HTTP
make test         # 75 tests (+1 opt-in Claude test): the pipeline end to end
cd batch && uv run --extra dev pytest -q && cd ..      # 5 tests: the batch loop
uv run --with pytest pytest platform/db/seed -q          # 4 tests: seed and guardrail
make eval         # the 150-case evaluation, mock: expect 150/150 (about 2 minutes, free)
CLAIMSENSE_LOCATION_CHECK=0 make eval                  # with the location check off: also 150/150
```

## 5. Claude instead of the mock agents (optional; Bedrock costs a few cents a run)

```bash
aws login --profile claimsense                  # sign in as the IAM user (a private window if the browser is on root)
aws sts get-caller-identity --profile claimsense
make stack BRAIN=bedrock                        # or: make runner BRAIN=bedrock in Option B
make agent CLAIM=CLM-2024-1800 AS=alice BRAIN=bedrock    # about 40 s, about $0.08
make golden                                     # the 150 cases on Claude: about 75 minutes and $10
```

## 6. Look inside

```bash
# API test page (paste a token as "Bearer <token>"): http://localhost:8000/docs
make token USER=alice                          # needs CLAIMSENSE_JWT_SECRET
curl -s localhost:8200/registry/v0/servers     # the MCP registry

# notes, reviews and the audit trail
docker exec claimsense-db psql -U claimsense -d claimsense -c \
  "SELECT n.note_id, n.claim_id, n.outcome, n.on_behalf_of, n.author, r.decision
     FROM claims_mgmt.claim_notes n LEFT JOIN claims_mgmt.note_reviews r USING (note_id) ORDER BY 1 DESC LIMIT 10;"
docker exec claimsense-db psql -U claimsense -d claimsense -c \
  "SELECT ts, user_id, actor, action, resource_id, decision, reason FROM claimsense.audit_log ORDER BY audit_id DESC LIMIT 20;"
```

Agent (OBO) tokens by hand, with Option B's API running:

```bash
ALICE=$(curl -s -X POST localhost:8000/api/v1/dev/login -H 'Content-Type: application/json' \
  -d '{"user_id":"alice"}' | python3 -c 'import sys,json; print(json.load(sys.stdin)["token"])')
OBO=$(curl -s -X POST localhost:8000/api/v1/obo/token -H "Authorization: Bearer $ALICE" \
  -H 'Content-Type: application/json' \
  -d "{\"claim_id\":\"CLM-2024-1800\",\"agent\":\"coverage\",\"run_id\":\"$(uuidgen)\"}" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["token"])')
curl -H "Authorization: Bearer $OBO" localhost:8000/api/v1/claims/CLM-2024-1800            # 200 its claim
curl -H "Authorization: Bearer $OBO" localhost:8000/api/v1/claims/CLM-2024-2092            # 403 bound to 1800
curl -H "Authorization: Bearer $OBO" localhost:8000/api/v1/claims/CLM-2024-1800/documents  # 403 no documents scope
curl -H "Authorization: Bearer $OBO" localhost:8000/api/v1/claims                          # 403 agents cannot list
```

## 7. Stop

`make stack-down` (Option A) or Ctrl+C in each terminal and `make down` (Option B). The data stays
until the next start reloads it; `make clean` deletes the database volume.
