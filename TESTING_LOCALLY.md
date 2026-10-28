# Testing ClaimSense locally (MacBook, no AWS needed)

Everything built so far runs on this Mac: PostgreSQL (Docker, port 5433), the data API (port 8000),
the runner (port 8100, runs the four agents), the MCP server (started per run over stdio) and the
console (port 3100). Docker Desktop must be running.

## 1. Start

**Option 1: the whole stack in Docker, one command**

```bash
cd ~/raju/CLAIMSENSE-AI
make stack                    # db, seed, api :8000, runner :8100, console :3100 (first build: a few minutes)
make stack BRAIN=bedrock      # the same, with Claude in the runner (needs a current `aws login --profile claimsense`)
make stack-logs               # follow the api, runner and console logs
```

`make stack` writes `.env` with a random token secret the first time. It stops `make up`'s database
first (both use the container name `claimsense-db` and port 5433), so `make eval` and `make test`
work against the stack's database too. Each start reloads the course data. A console sign-in from
before a new secret shows "Missing, expired or invalid token": sign out and in again.

**Option 2: each service in its own terminal** (faster to change code)

```bash
# Terminal 1: database + data API
cd ~/raju/CLAIMSENSE-AI
make up                                   # only if the database is not already running
export CLAIMSENSE_JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
CLAIMSENSE_DEV_LOGIN=1 make api           # http://localhost:8000

# Terminal 2: runner (what the Run assessment button calls; mock agents, no AWS)
cd ~/raju/CLAIMSENSE-AI
make runner                               # http://localhost:8100/health

# Terminal 3: console
cd ~/raju/CLAIMSENSE-AI
make web                                  # http://localhost:3100
```

Order: database first; the API, runner and console in any order after that.

## 2. Test

**A. Console** (http://localhost:3100): sign in by user id and compare.

| Sign in as | Expect |
|---|---|
| alice | 6 claims; `/claims/CLM-2024-1873` shows "Not available" |
| david | 6 claims; `/claims/CLM-2024-2822` shows the lapsed policy (ended 2024-01-28, loss 2024-01-31) |
| bob | all 20 claims |
| carol | 3 claims; `/documents/DOC-00007` shows the pending-OCR notice |
| eve | 4 claims (2 assigned + 2 total-loss candidates) |
| frank | refused (suspended) |

The Policy manual page never shows `CLS-ADM-013`, the injected clause, whatever you search for.

**Run assessment** (top of every claim page): click it to run the four agents and write a draft note.
Try `/claims/CLM-2024-1800` as alice (APPROVE) and `/claims/CLM-2024-2822` as david (DENY). Each note
shows its citations; "How this was reached" shows the code facts, the signals, and each agent's output.
Every click adds a new note. If the runner is not running, the page says so.

**B. API test page:** http://localhost:8000/docs. Paste a token into `authorization` as `Bearer <token>`.
Get one with `make token USER=alice` (same `CLAIMSENSE_JWT_SECRET` as the API) or from `/api/v1/dev/login`.

**C. Agent (OBO) tokens by hand** (another terminal):

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
curl -H "Authorization: Bearer $OBO" "localhost:8000/api/v1/clauses?q=collision"           # 200 coverage may search
curl -H "Authorization: Bearer $OBO" localhost:8000/api/v1/claims                          # 403 agents cannot list
```

The OBO token expires after 5 minutes; ask for a new one if you get 401.

**D. Automated tests** (need only the database):

```bash
make api-test     # 67 tests
make mcp-test     # 6 tests
make test         # 38 tests (+1 Bedrock test, opt-in): the agent pipeline end to end (starts its own API)
uv run --with pytest pytest platform/db/seed -q    # 4 tests
```

**E. The evaluation suite** (60 cases; only the database is needed, it starts its own API):

```bash
make eval                    # mock: about 2 minutes, free; expect 58/60 (2 proposed rules fail by design)
make eval BRAIN=bedrock      # Claude: about 30 minutes and $3.50
CLAIMSENSE_LOCATION_CHECK=1 make eval   # with the loss-location check on: expect 60/60
```

**F. Claude instead of the mock agents (Bedrock; a few cents and about 40 s a run)**

```bash
aws sts get-caller-identity --profile claimsense   # must show user/rramachandra33; if expired:
aws login --profile claimsense                     # sign in as the IAM user (use a private window)
make agent CLAIM=CLM-2024-1800 AS=alice BRAIN=bedrock
make runner BRAIN=bedrock                          # then Run assessment in the console uses Claude
```

CLM-2024-1800's FNOL and police report give different loss locations (so does every police report
in the course data). By default that is not a reason to FLAG, and Claude is told so; with
`CLAIMSENSE_LOCATION_CHECK=1` code compares the two locations and a mismatch is a FLAG
(CLS-FRD-007). Addresses in a note show as `[address]`.

**G. Run the four agents from the terminal** (mock brain, no AWS; with `make api` running):

```bash
make agent CLAIM=CLM-2024-1800 AS=alice      # APPROVE, cites CLS-COLL-001, CLS-PER-006, CLS-DED-004
make agent CLAIM=CLM-2024-2822 AS=david      # DENY: loss 3 days after the policy ended (CLS-PER-006)
make agent CLAIM=CLM-2024-1873 AS=alice      # run failed: claim not available (carol's claim)
make agent CLAIM=CLM-2024-1873 AS=bob        # FLAG (provisional precedence: FLAG and ROUTE both signalled)
cd agent && uv run claimsense-agent run --claim CLM-2024-1800 --user alice --demo-bad-draft
                                             # cites made-up CLS-XXX-999: DENY, decision_source deterministic_fallback
```

Each run prints a trace (code facts, each agent, the draft check, the note write) and writes one note.
The notes appear on the claim page in the console. Or see them in the database:

```bash
cd platform/db && docker compose exec claimsense-db psql -U claimsense -d claimsense -c \
  "SELECT note_id, claim_id, outcome, cited_clauses, created_at FROM claims_mgmt.claim_notes ORDER BY note_id DESC LIMIT 10;"
```

**H. See the audit trail:**

```bash
cd platform/db && docker compose exec claimsense-db psql -U claimsense -d claimsense -c \
  "SELECT ts, user_id, actor, action, resource_id, decision, reason FROM claimsense.audit_log ORDER BY audit_id DESC LIMIT 20;"
```

## 3. Stop

Docker stack: `make stack-down` (data kept until the next start reloads it).

Separate terminals: Ctrl+C in each terminal. `make down` stops the database (data kept); `make up`
brings it back (it also reloads the course data, which clears drafts and the audit log).
