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
| Check the draft | pipeline code | none | citations retrieved in this run, a citation or a DENY reason, no APPROVE against code's findings |
| Write the note | pipeline code | the adjuster's token, with an `Idempotency-Key` | one assessment and one append-only claim note |

A draft that fails a check is replaced by code's own decision (`decision_source:
deterministic_fallback`). If no clause can be cited, the outcome is DENY (open question 3).

## Brains

* `mock` (default): deterministic stand-ins in `agents/mock.py`. They make the same tool calls a
  real agent would, through the real MCP server and API, and replace only the model's judgment
  with simple rules. No model, no key, no AWS, and every run gives the same result.
* `bedrock`: Claude on Amazon Bedrock through the OpenAI Agents SDK. **Next step, not built yet.**

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
                                                    # the code checks replace a bad draft
cd agent && uv run claimsense-agent claims --user bob   # the claims bob may read
```

Each run adds a new note (re-runs never overwrite). `make up` reloads the course data and clears them.

## The runner (the console's Run assessment button)

```bash
make runner      # http://localhost:8100, needs make api
```

`POST /runs {"claim_id": ...}` with the adjuster's token runs the pipeline as that adjuster and
returns the run result. The runner is a client of the data API like any other: it forwards the
token and has no access rules or secrets of its own. The brain comes from `CLAIMSENSE_BRAIN`
(default `mock`).

## Tests

```bash
make test        # or: cd agent && uv run --extra dev pytest -q
```

The tests start their own API on a free port, so `make api` does not need to be running; the
database does (`make up`). They clean up the notes they write.

## Provisional, still to decide

* **Precedence** (open question 2): when several outcomes are signalled, `PROVISIONAL_PRECEDENCE`
  in `facts.py` picks DENY, then FLAG, then ROUTE. A documentation gap on its own counts as FLAG.
  Both are placeholders until the precedence decision; the cases are in `evals/precedence_cases.json`.
* **Fraud threshold**: vendor score 0.70.

## Files

```
src/claimsense_agent/
├── cli.py          run / claims commands
├── runner.py       the runner service the console calls (POST /runs)
├── pipeline.py     the run: facts, four agents, draft checks, note write
├── facts.py        code facts and the outcome signals (same rules as scripts/import_course_fixtures.py)
├── schemas.py      typed outputs for each agent and for the run
├── api.py          the pipeline's own API calls (adjuster's token), with note-write retries
├── tools.py        one agent's MCP session (its OBO token)
├── brain.py        mock or bedrock
├── trace.py        on-screen trace (from the Week 15 sample)
└── agents/mock.py  the four mock agents
```
