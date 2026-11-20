# Policy manual search — UI → backend workflow (and the agents' clause search)

## Example used

1. **alice** clicks the clause link **CLS-FRD-007** on her note for CLM-2024-1800. The console opens
   `/clauses?q=CLS-FRD-007` and shows that one clause.
2. **alice** types **fraud indicators police report** in the policy manual search box: a word search,
   best matches first.
3. The **risk agent**, during a run, calls `search_clauses("fraud indicators")` through the MCP server;
   the result is logged under its run, so the drafter may cite it.
4. Nobody can find **CLS-ADM-013**: it is the planted chunk with injected instructions, quarantined
   when the manual was loaded.

Source tests: `platform/db/seed/test_seed.py` (the injected chunk is quarantined; all 12 real clauses
are indexed; every clause lands in exactly one table), `api/tests/test_data_routes.py`,
`mcp_server/tests/test_tools.py`; evaluation cases EV-045 (claim text tries to steer the search),
EV-047 to EV-049 (made-up, quarantined and unretrieved citations).

**Important architectural note:** only `claimsense.clause_index` is ever searched or read. A clause
the load-time guardrail quarantined answers exactly like one that never existed (no result, 404), so
it can never be returned, retrieved or cited.

---

## 0. Loading the manual (once, at seed time)

| Step | Function | File |
|---|---|---|
| Read the clauses | `build_clauses()`: the 12 manual clauses plus the injected chunk in `injected_clauses.json` | `platform/db/seed/build_seed.py` |
| Check each | `find_injection(text)`: `INJECTION_PATTERNS`: "ignore previous instructions", "system instruction", addressing "the assistant" / "the AI", "overrides the manual", "do not cite", "approve all claims" | `platform/db/seed/guardrail.py` |
| Split | `split_clauses()`: clean → `claimsense.clause_index`; suspicious → `claimsense.clause_quarantine` with the matching pattern as the reason | `platform/db/seed/build_seed.py` |
| Index | `search TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', title \|\| ' ' \|\| text))` with a GIN index | `platform/db/schema.sql` |

## 1. User action in the browser

| Step | Function | File |
|---|---|---|
| Clause link on a note | `ClauseLink({ id })` → `/clauses?q=CLS-FRD-007` | `platform/web/src/app/claims/[id]/NotesList.tsx` |
| Search box | the policy manual page, `?q=…` | `platform/web/src/app/clauses/page.tsx` |
| Page | `ClausesPage({ searchParams })`: `requireSession()`, then `findClauses(q)` | `platform/web/src/app/clauses/page.tsx` |

## 2. Frontend request

`findClauses(q)` (`platform/web/src/app/clauses/page.tsx`):

| Input | Matches `CLAUSE_ID = /^CLS-[A-Z]+-\d+$/i`? | Call |
|---|---|---|
| `CLS-FRD-007` | yes | `apiGet("/api/v1/clauses/CLS-FRD-007")`; a 404 shows as "no clause" |
| `fraud indicators police report` | no | `apiGet("/api/v1/clauses?q=…&top_k=8")` |

An id goes to the lookup because the word search splits `CLS-FRD-007` into `cls`, `frd`, `007`, which
the clause text does not contain (the reason clause links found nothing before 2026-11-05).

## 3. API

| Step | Function | File |
|---|---|---|
| Search | `search_clauses(q, top_k, run_id, agent)` — `GET /api/v1/clauses` | `api/src/claimsense_api/main.py` |
| One clause | `get_clause(clause_id, run_id, agent)` — `GET /api/v1/clauses/{clause_id}`; 404 if not in `clause_index` | `api/src/claimsense_api/main.py` |
| Caller | `require_user()`; an agent needs scope `clauses:search` (`check_agent`): coverage and risk have it, reader and drafter do not | `api/src/claimsense_api/main.py`, `obo.py` |
| Limits | `q` 3–500 characters, `top_k` 1–8 | `api/src/claimsense_api/main.py` |
| Query | `plainto_tsquery('english', q)` with `&` turned into `\|` (match **any** word), `ts_rank` score, best first | `api/src/claimsense_api/main.py` |
| Run log | with a `run_id` (always taken from the OBO token for an agent, whatever the request says): `INSERT INTO claimsense.retrieval_log (run_id, agent, query, clause_ids)` | `api/src/claimsense_api/main.py` |
| Audit | the query and the clause ids returned | `api/src/claimsense_api/audit.py` |

## 4. The agents' path to the same search

```text
risk agent (Claude) → tool search_clauses("fraud indicators")       agents/bedrock.py make_tools
  → AgentTools.call("search_clauses")  records the clause ids        agent/…/tools.py
  → MCP server search_clauses(query, top_k=4)                        mcp_server/…/server.py
  → GET /api/v1/clauses?q=… with the risk agent's OBO token
  → search_clauses: scope ✓, run_id := the token's run → retrieval_log
```

Two checks then use that log: the pipeline's `check_citations()` / `check_draft()` (a draft may cite
only clauses retrieved in its run) and the API's `check_citations_were_retrieved()` when the note is
written.

## 5. Rendering

The page lists each clause with its id, title and text; a search shows each result's score, a clause
id lookup shows "clause id" instead.

## Call chain at a glance

```text
ClauseLink / search box → ClausesPage → findClauses
  → id?   apiGet /api/v1/clauses/{id} → get_clause → clause_index (404 if absent or quarantined)
  → words apiGet /api/v1/clauses?q=  → search_clauses → ts_rank over clause_index (any word)
                                       → retrieval_log (runs only) → log_audit
```
