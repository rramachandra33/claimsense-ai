# AWS deployment evidence: annotated screenshots

Captured on 19 Nov 2026 from the deployed system (us-east-1, account 5794-0946-6114), the AWS
console, the ClaimSense console and GitHub Actions. Each image has a title, what it shows, and
numbered boxes. All 21 in one file: `../ClaimSense-AI-AWS-Evidence-Screenshots.pdf`.
`annotate.py` rebuilds them from `raw/`.

| # | Shows | Brief (Submission 2, item 6) |
|---|---|---|
| 01 | EC2 instance running the stack (t3.small, instance role, no keys) | the AWS deployment |
| 02 | AgentCore runtime `claimsense_runner`: Active; the drill's errors | the AWS deployment |
| 03 | Lambda `claimsense-api` (the data API the agents call) | the AWS deployment |
| 04 | Cognito pool `claimsense-users` and the four role groups | the AWS deployment |
| 05 | Alarms: BadRuns in alarm since the drill (14:24:29 UTC), SlowRuns OK | CloudWatch alarms |
| 06 | BadRuns graph: 55.6% against the 25% threshold | CloudWatch alarms |
| 07 | Dashboard *Experience*: p95 latency, call volume and failures, Lambda errors | CloudWatch dashboards |
| 08 | Dashboard *Quality*: CI gate pass rate, live error rates, decisions by outcome | CloudWatch dashboards |
| 09 | Dashboard *Economics*: model cost per resolution | CloudWatch dashboards |
| 10 | ECR: the four repositories | the container registry |
| 11 | ECR images tagged by commit (`96c07fd` live, `d08d6f0`) | the container registry |
| 12 | Lambda Claims API request log during the drill | log records |
| 13 | Batch schedule built and disabled (decision of 2026-11-19) | the AWS deployment |
| 14 | Audit log: one run's agents under their own tokens; the latest refusals | audit records |
| 15 | CI run on commit `96c07fd`: tests and gate, then image push | the CI run |
| 16 | The gate's scorecard: 150/150, every family | the CI run |
| 17 | The running console: alice's queue (6 claims) | the running console |
| 18 | A claim's notes: model draft, code check, adjuster decides; the drill's failure | the running console |
| 19 | "How this was reached": code's facts beside the model's judgement | the running console |
| 20 | Refusal on entitlement: another adjuster's claim, no data | the running console |
| 21 | The policy manual: a cited clause opened by its id | the running console |

Notes: 14 is real `psql` output from the instance, drawn as a terminal (the database has no AWS
console page). Red permission banners in 03, 04 and 06 are console features the deploy user has no
rights to (`lambda:ListFunctions`, Cognito replicas, `cloudwatch:DescribeAlarmHistory`), not
errors in ClaimSense.
