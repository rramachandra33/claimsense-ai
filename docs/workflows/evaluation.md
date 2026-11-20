# Evaluation run — command → backend workflow

## Example used

```bash
make eval            # 60 cases, mock agents: 60/60, free, about 45 s (the CI gate)
make golden          # 60 cases on Claude: 56/60 on 2026-11-09, $3.97, 21 minutes
cd agent && AWS_PROFILE=claimsense uv run --extra dev claimsense-agent eval \
    --brain bedrock --cases EV-022,EV-024,EV-028,EV-038     # the 4 reruns after the fix: 4/4, $0.28
```

One case followed through: **EV-028** "Vendor fraud score 0.69: below the threshold". It copies course
claim CLM-2024-3041 with `fraud_risk_score` 0.69 and expects **APPROVE** (0.70 is the threshold).

Source tests: `agent/tests/test_evaluate.py`. Report: `docs/ClaimSense-AI-Golden-Run-2026-11-09.pdf`.

**Important architectural note:** the evaluation runs the **real pipeline** against the **real data
API** and PostgreSQL, not a simulation. Only the database must be up (`make up`): the run starts its
own data API on a free port and its own MCP server. Cases that change a claim run on a **temporary
copy** that is removed afterwards, so the 20 course claims are never modified.

---

## 1. Command

| Step | Function | File |
|---|---|---|
| Make targets | `eval: claimsense-agent eval --brain $(BRAIN) --min-pass 0.9`; `golden: make eval BRAIN=bedrock` | `Makefile` |
| CLI | `claimsense-agent eval [--brain] [--cases] [--family] [--min-pass]` | `agent/src/claimsense_agent/cli.py` |
| Suite | `run_suite(brain, case_ids, family, min_pass)` | `agent/src/claimsense_agent/evaluate.py` |
| Database up? | `database_is_up()`, otherwise "The database is not running. Start it with: make up" | `agent/src/claimsense_agent/local_api.py` |
| Services | `LocalApi`: the data API and the MCP server (with its registry) on free ports, in threads | `agent/src/claimsense_agent/local_api.py` |
| Cases | `load_cases()` from `evals/cases.json` (60: baseline 20, variation 22, attack 9, access 4, token 5) | `agent/src/claimsense_agent/evaluate.py` |

## 2. One case: `run_case(case, brain, groups)`

| Step | Function | File |
|---|---|---|
| Token cases (family *token*) | `token_check(name)`: mint an OBO token for alice's claim and try what it must not do (another claim, out of scope, list claims, write a note, expired) → expect 403/401 | `agent/src/claimsense_agent/evaluate.py` |
| Temporary claim | `create_temp_claim(case, number)`: copy the base claim, its policy and documents as `CLM-9000-0028`, `POL-EVL-00028`, `DOC-9028x`; apply `changes` (claim, policy, documents: pending, remove, add, set_text) | `agent/src/claimsense_agent/evaluate.py` |
| Ids in the text | `with_new_ids(text, new_ids)`: the copied documents' text names the copy's claim, policy and documents, not the original's (fixed 2026-11-09: before, Claude saw a claim form for CLM-2024-3041 on claim CLM-9000-0028 and rightly flagged it) | `agent/src/claimsense_agent/evaluate.py` |
| Run | `ApiClient(make_dev_token(case["user"], group))` → `run_assessment(client, claim_id, brain, bad_citation=…)`; attack cases EV-047 to EV-050 plant a bad draft through `bad_citation` | `agent/src/claimsense_agent/evaluate.py`, `pipeline.py` |
| Note | the summary and deny reason; `redact()` on them counts personal details that got through | `agent/src/claimsense_agent/evaluate.py` |
| Other claims read | from `claimsense.audit_log` for this run: any allowed read of a claim or document other than this claim's | `agent/src/claimsense_agent/evaluate.py` |
| Clean up | `remove_run(run_id)` (note, review, assessment, retrieval log) and `remove_temp_claim(number)` | `agent/src/claimsense_agent/evaluate.py` |

## 3. Scoring: `score(case, result)`

Each case's `expect` may set: `status`, `outcome`, `outcome_any`, `outcome_not`, `decision_source`,
`must_cite`, `must_not_cite`, `problem_contains`, `no_personal_details`, `no_other_claim_reads`; with the
location check on, `with_location_check` overrides some expectations. A case passes when the failure
list is empty. EV-028: `outcome APPROVE` → after the fix, APPROVE ✓.

## 4. Summary, results file, gate

| Step | Function | File |
|---|---|---|
| Line per case | `print_result()`: ✓/✗, family, outcome, "(fallback)", seconds, cost, title, and each failure | `agent/src/claimsense_agent/evaluate.py` |
| Summary | `summarise()` / `print_summary()`: by family, several-outcome cases with their precedence, proposed rules, pass rate, cost, time | `agent/src/claimsense_agent/evaluate.py` |
| File | `evals/results/<time>-<brain>.json` (not in git): every result with the note, tokens and cost | `agent/src/claimsense_agent/evaluate.py` |
| Metrics | with `CLAIMSENSE_METRICS=1`, for a full run only (no `--cases` or `--family`): `EvalPassRate`, `EvalCases`, `EvalCostUsd` | `agent/src/claimsense_agent/metrics.py` |
| Gate | exit code 1 when the pass rate is below `--min-pass` (0.9); 2 when the database is down or no case matches | `agent/src/claimsense_agent/evaluate.py` |

## 5. In CI

`.github/workflows/ci.yml`, job steps: database and course data → seed, API, MCP, pipeline and batch
tests → **Evaluation gate** `claimsense-agent eval --brain mock --min-pass 0.9` → the results file kept
as the `eval-results` artifact → on `main`, build and push the images. A push that breaks a decision
rule fails here before anything is deployed.

## Call chain at a glance

```text
make golden → make eval BRAIN=bedrock → claimsense-agent eval → run_suite
  → database_is_up → LocalApi (API + MCP on free ports) → load_cases
  → for each case: run_case
        token case → token_check (expect refusal)
        otherwise  → create_temp_claim (with_new_ids) → run_assessment (real pipeline, real API)
                   → read the note, audit log → remove_run → remove_temp_claim
     → score → print_result
  → summarise → print_summary → evals/results/…json → exit 1 if pass rate < 0.9
```
