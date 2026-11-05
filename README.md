# ClaimSense AI

A claims adjudication co-pilot for a motor insurer (FDE capstone). Given a claim, it returns a first
decision (APPROVE, FLAG, ROUTE or DENY), the reasoning, and the evidence it rests on. A licensed
adjuster confirms every outcome. All data is synthetic.

- **Deterministic code** owns identity, access control, policy dates and money.
- **Model judgment** (four agents: read the file, check coverage, assess risk, draft decision) is always cited.
- **Stack:** Python, OpenAI Agents SDK with Claude on Amazon Bedrock, PostgreSQL behind an MCP server,
  Amazon Cognito, containers, CI with an evaluation gate, AWS (EC2).

## Run it

```bash
make stack        # the whole stack in Docker; console on http://localhost:3100 (sign in as alice)
make eval         # the 60-case evaluation (mock brain, free)
```

Run and test everything locally, from scratch: `TESTING_LOCALLY.md`. Deploy and test on AWS, from
scratch: `DEPLOY_AND_TEST_ON_AWS.md`. Every decision, dated: `DECISIONS.md`. `make help` lists every target.

## Status

Working locally: data API, MCP server, four agents (mock and Claude on Bedrock), runner, console,
evaluation suite, and the Docker stack. Still to do: CI gate and image push, AWS deployment,
Cognito. Roadmap: `docs/ClaimSense-AI-Roadmap-and-Status.pdf`.

## Repository layout (current)

| Path | Contents |
|---|---|
| `api/` | The data API: token check, access rule and audit in front of PostgreSQL |
| `mcp_server/` | The MCP server the agents use (read-only tools that call the API with the agent's token) |
| `agent/` | The four agents, the pipeline, the runner service and the evaluation runner |
| `platform/db/`, `platform/web/` | Database schema and seed; the Ops Console (Next.js) |
| `docker-compose.yml` | The whole stack (`make stack`); each service has its own `Dockerfile` |
| `docs/` | Design documents as PDFs: overview, scope, open questions and answers, workflow diagram, OBO permissions, PostgreSQL plan, users and access rules, reuse plan and more |
| `data/course_fixtures/` | Course-supplied fixtures (core dataset): `source/` unchanged, plus typed JSON, clauses and code facts built by `scripts/import_course_fixtures.py` |
| `data/identity/users.json` | Users, groups and the access rule |
| `data/synthetic/` | Earlier generated dataset (used only by `evals/legacy/`) |
| `evals/` | The 60-case evaluation suite (`cases.json`), `precedence_cases.json`, and the old 150 cases in `legacy/` |
| `frontend/` | First React prototype of the adjuster console (simulated backend) |
| `data-visualization/` | Case Explorer and workflow diagram pages |
| `scripts/` | Data generator and course-fixture importer |
| `CLAIMSENSE-CAPSTONE.pdf`, `claimsense-walkthrough-slides.pdf` | The course brief and slides |

## Regenerate the course data

```bash
python3 scripts/import_course_fixtures.py   # needs pdftotext (brew install poppler)
```
