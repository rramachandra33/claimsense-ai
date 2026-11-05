# ClaimSense assessment pipeline

Four agents assess one claim, in an order fixed by code, and code writes one draft note for the
adjuster to confirm.

```
code facts → reader → coverage → risk → drafter → check the draft → write the note
```

| Step | Who | Reaches data with | Does |
|---|---|---|---|
| Code facts | pipeline code | the adjuster's token, through the API | dates, money, total-loss ratio, document checks (`facts.py`) |
| 1 · Reader | agent | its own OBO token, through MCP | reads every document whose OCR has finished |
| 2 · Coverage | agent | its own OBO token, through MCP | checks coverage and searches the policy manual for the clauses to cite |
| 3 · Risk | agent | its own OBO token, through MCP | fraud indicators (CLS-FRD-007), searches for the fraud clause |
| 4 · Drafter | agent | its own OBO token, through MCP | drafts the outcome, summary and citations |
| Check the draft | pipeline code | the adjuster's token, for clause lookups | citations retrieved in this run and real, a citation or a DENY reason, no APPROVE against code's findings |
| Write the note | pipeline code | the adjuster's token, with an `Idempotency-Key` | one assessment and one append-only claim note |

A draft that fails a check is replaced by code's own decision (`decision_source:
deterministic_fallback`). Two cases are always DENY: the draft cites a clause that does not exist in
the policy manual (a made-up citation), or no clause can be cited at all (open question 3).

The coverage and risk agents' citations are checked too, as soon as each agent finishes: a clause
that no search returned in the run is removed from its output (and listed in the run's problems and
the note's `citation_problems`), so the drafter is never offered it.

## Brains

* `mock` (default): deterministic stand-ins in `agents/mock.py`. They make the same tool calls a
  real agent would, through the real MCP server and API, and replace only the model's judgment
  with simple rules. No model, no key, no AWS, and every run gives the same result.
* `bedrock`: Claude on Amazon Bedrock through the OpenAI Agents SDK (`agents/bedrock.py`), the
  Week 15 sample's pattern (`LitellmModel("bedrock/converse/…")`). Haiku 4.5 reads and assesses
  risk; Sonnet 4.5 checks coverage and drafts. About 30–45 s a run. Each agent's tools are thin
  wrappers around its own MCP session, so every call still goes through the MCP server and the
  API under that agent's OBO token. Agents SDK tracing is turned off (it would upload claim data
  to OpenAI), and LiteLLM does not load `.env` files.

  Locally it uses the AWS profile `claimsense` (`aws login --profile claimsense`); on EC2 the
  instance role. Run it with `BRAIN=bedrock`:

  ```bash
  make agent CLAIM=CLM-2024-1800 AS=alice BRAIN=bedrock
  make runner BRAIN=bedrock          # the console's Run assessment button then uses Claude
  ```

### Tokens and cost

Every run records each agent's model, model calls and tokens, priced from `pricing.py` (AWS
on-demand prices for the `us.` profiles, us-east-1). The CLI prints the total, the runner returns
it, and the console shows a per-agent table under "How this was reached". Measured on three
course claims: about $0.06–0.08 and 23–33k input tokens per assessment.

### Personal details

The note goes into the client's claims system, so code removes street addresses, phone numbers
and emails from its summary and deny reason before writing it (`redact.py`). Names cannot be
caught by a pattern; the agents are told to leave them out. Agent outputs keep what the agents
wrote: they stay in ClaimSense's assessment record, visible only to people who may read the claim.

## Run

Start the database and the API first (see `TESTING_LOCALLY.md` at the repo root):

```bash
make up
export CLAIMSENSE_JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
CLAIMSENSE_DEV_LOGIN=1 make api
```

Then, in another terminal:

```bash
make agent CLAIM=CLM-2024-1800 AS=alice             # APPROVE
make agent CLAIM=CLM-2024-2822 AS=david             # DENY: loss 3 days after the policy ended
make agent CLAIM=CLM-2024-1873 AS=alice             # refused: carol's claim
cd agent && uv run claimsense-agent run --claim CLM-2024-1800 --user alice --demo-bad-draft
                                                    # a made-up citation (CLS-XXX-999): DENY
cd agent && uv run claimsense-agent claims --user bob   # the claims bob may read
```

Each run adds a new note (re-runs never overwrite). `make up` reloads the course data and clears them.

## The runner (the console's Run assessment button)

```bash
make runner      # http://localhost:8100, needs make api + make mcp
```

`POST /runs {"claim_id": ...}` with the adjuster's token runs the pipeline as that adjuster and
returns the run result. The runner is a client of the data API like any other: it forwards the
token and has no access rules or secrets of its own. The brain comes from `CLAIMSENSE_BRAIN`
(default `mock`).

### The AgentCore Runtime contract

The same service answers the two routes Amazon Bedrock AgentCore Runtime calls, so the same image
runs there unchanged (AgentCore runs it on port 8080: `RUNNER_PORT=8080`):

| Route | What |
|---|---|
| `GET /ping` | `{"status": "Healthy"}` |
| `POST /invocations` | `{"claim_id": ..., "user_token": ...}`: the same run as `/runs` |

On AgentCore the caller signs the request with AWS credentials (SigV4), which uses the
`Authorization` header, so the adjuster's token travels in the body as `user_token`. The access
rules are unchanged: the API still decides what that adjuster may see.

```bash
docker run --rm -p 8080:8080 -e RUNNER_PORT=8080 --network claimsense_default \
  -e CLAIMSENSE_API_URL=http://api:8000 \
  -e CLAIMSENSE_MCP_REGISTRY_URL=http://mcp:8200/registry/v0/servers claimsense-runner
curl localhost:8080/ping
```

## The loss-location check (off by default)

`CLAIMSENSE_LOCATION_CHECK=1` makes code compare the `Location` line of the FNOL with the police
report's (`facts.locations_match`). A mismatch is a FLAG under CLS-FRD-007. Off, there is no such
signal and the Claude risk and drafter agents are told not to FLAG for it: in the course data every
police report (CLM-2024-1800, 1946, 2019, 2092) gives a different location from its FNOL.

## Evaluation

`make eval` runs the 60 cases in `evals/cases.json` through the real pipeline and scores them
(`evaluate.py`; see `evals/README.md`). On the mock brain it is free and is the CI gate (pass rate
0.9); `make eval BRAIN=bedrock` runs them on Claude. The run starts its own API, puts each changed
claim on a temporary copy, and removes everything it wrote.

## Tests

```bash
make test        # or: cd agent && uv run --extra dev pytest -q
```

The tests start their own API on a free port, so `make api` does not need to be running; the
database does (`make up`). They clean up the notes they write. One test calls Claude for real and
runs only when asked:

```bash
cd agent && CLAIMSENSE_BEDROCK_TESTS=1 AWS_PROFILE=claimsense uv run --extra dev pytest -q tests/test_bedrock.py
```

## Precedence (decided 2026-11-04)

When several outcomes are signalled, the note carries the first of **DENY, FLAG, ROUTE, APPROVE**
(`PRECEDENCE` in `facts.py`). No cover ends it; fraud review comes before any specialist or payment;
a specialist comes before payment. A documentation gap on its own counts as FLAG (CLS-DOC-009).

Nothing is dropped: after the draft checks, code adds to the note's summary (`note_additions`)

* **Also needs:** each signal for another outcome, with its clause (for example a senior adjuster
  on a FLAG, or an injury on a DENY);
* **Pending documentation:** each documentation gap, with its clause;
* on a FLAG that rests on documentation alone: "Code found no fraud indicators: this FLAG is for
  the pending documentation."

Code writes these lines, so no draft can leave them out. The three original cases are in
`evals/precedence_cases.json`.

## VIN mismatch (decided 2026-11-04)

When the claim's VIN differs from the policy's, code adds a CLS-FRD-007 fraud indicator: "the
claim's VIN (ending 004352) does not match the VIN on the policy" (only the last six characters go
on the note). It is a FLAG, so the precedence rule applies: on a lapsed policy the note is a DENY
that lists the FLAG under "Also needs". The risk agent's token cannot read the policy, so code does
this check, not the agent.

## Unmapped loss type (decided 2026-11-04)

`LOSS_CATEGORY` in `facts.py` maps each loss type to collision or comprehensive. A type it does not
list (for example "Mechanical breakdown") gets no cover decision from code: it is a ROUTE signal,
"loss type '…' is not mapped to collision (CLS-COLL-001) or comprehensive (CLS-COMP-002) cover, so
an adjuster must decide which cover applies, if any", cited under CLS-COMP-002. Both insuring
clauses are retrieved in the run. A new loss type is added to `LOSS_CATEGORY`, not guessed.

## Provisional, still to decide

* **Fraud threshold**: vendor score 0.70.

## Files

```
src/claimsense_agent/
├── cli.py          run / claims commands
├── runner.py       the runner service: POST /runs (console), GET /ping + POST /invocations (AgentCore)
├── pipeline.py     the run: facts, four agents, draft checks, note write
├── facts.py        code facts and the outcome signals (same rules as scripts/import_course_fixtures.py)
├── schemas.py      typed outputs for each agent and for the run
├── api.py          the pipeline's own API calls (adjuster's token), with note-write retries
├── tools.py        one agent's MCP session (its OBO token)
├── brain.py        mock or bedrock
├── redact.py       removes addresses, phones and emails from the note
├── pricing.py      token prices per model and the cost of a run
├── evaluate.py     the evaluation run: cases, temporary claims, scoring, the report
├── local_api.py    starts the data API in-process (tests and evaluation)
├── trace.py        on-screen trace (from the Week 15 sample)
├── agents/mock.py     the four mock agents
└── agents/bedrock.py  the four Claude agents (Bedrock, Agents SDK)
```
