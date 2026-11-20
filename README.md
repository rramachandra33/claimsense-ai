# ClaimSense AI

A claims adjudication co-pilot for a motor insurer (FDE capstone). Given a claim, it returns a first
decision (APPROVE, FLAG, ROUTE or DENY), the reasoning, and the evidence it rests on. A licensed
adjuster confirms every outcome. All data is synthetic.

- **Deterministic code** owns identity, access control, policy dates and money.
- **Model judgment** (four agents: read the file, check coverage, assess risk, draft decision) is always cited.
- **Stack:** Python, OpenAI Agents SDK with Claude on Amazon Bedrock, PostgreSQL behind an MCP server,
  Amazon Cognito, containers, CI with an evaluation gate, AWS (EC2).

## Live deployment (AWS us-east-1)

- **ClaimSense console:** https://claimsenseai.rajur-dev.com (sign in with the accounts given in the
  submission form; start with `docs/HANDOVER.md`)
- **Design document and recorded demo:** click the ClaimSense logo (on the sign-in screen or at
  the top of the sidebar) for a menu with **Design Document** (`/docs/design.html`) and
  **Recorded Demo** (`/presentation/ClaimSense_Capstone_Presentation.mp4`, 8 min 42 s). Caddy
  serves both from `/opt/claimsense/site/` on the instance; the video is not in the repository.
  The logo is `platform/web/src/components/Logo.tsx`, the menu `BrandMenu.tsx`.
- **CloudWatch dashboards** (sign-in to the AWS account required):
  - [ClaimSense-Experience](https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#dashboards/dashboard/ClaimSense-Experience):
    p95 latency, call volume, failures, Lambda errors
  - [ClaimSense-Quality](https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#dashboards/dashboard/ClaimSense-Quality):
    evaluation pass rate against the 90% gate, fallbacks, decisions by outcome
  - [ClaimSense-Economics](https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#dashboards/dashboard/ClaimSense-Economics):
    model cost per resolution, tokens
  - [Alarms](https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#alarmsV2:?search=ClaimSense):
    ClaimSense-BadRuns and ClaimSense-SlowRuns

  Without AWS access, the annotated screenshots of these pages are in
  `docs/ClaimSense-AI-AWS-Evidence-Screenshots.pdf` (S05–S09).

## Run it

```bash
make stack        # the whole stack in Docker; console on http://localhost:3100 (sign in as alice)
make eval         # the 150-case evaluation (mock brain, free)
```

Run and test everything locally, from scratch: `TESTING_LOCALLY.md`. Deploy and test on AWS, from
scratch: `DEPLOY_AND_TEST_ON_AWS.md`. Every decision, dated: `DECISIONS.md`. `make help` lists every target.

## Status

Built and deployed on AWS: data API (EC2 and Lambda), MCP server and registry (Lambda), four
agents on AgentCore (Claude on Bedrock; mock agents locally), console with Confirm/Reject, scheduled
batch assessment, Amazon Cognito sign-in (`deploy/cognito/`), CI with the evaluation gate, and
CloudWatch dashboards and alarms with email notification. Evaluated (150 cases, 148/150 on Claude),
drilled (recovered in 3 min 12 s), with a runbook and a handover pack: `docs/HANDOVER.md`. Final
submission: tag `submission-2`.

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
| `evals/` | The 150-case evaluation suite (`cases.json`), `precedence_cases.json`, and the old 150 cases in `legacy/` |
| `frontend/` | First React prototype of the adjuster console (simulated backend) |
| `data-visualization/` | Case Explorer and workflow diagram pages |
| `scripts/` | Data generator and course-fixture importer |
| `CLAIMSENSE-CAPSTONE.pdf`, `claimsense-walkthrough-slides.pdf` | The course brief and slides |

## Regenerate the course data

```bash
python3 scripts/import_course_fixtures.py   # needs pdftotext (brew install poppler)
```
