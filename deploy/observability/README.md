# Observability: traces, metrics, three dashboards, two alarms

| What | Where it comes from | Where it goes |
|---|---|---|
| Traces: every step of a run is a span (code facts, rule clauses, reader, coverage, risk, drafter, check draft, write note), with the HTTP and Bedrock calls inside | `trace.Tracer` spans are OpenTelemetry spans; on AgentCore the runner starts under `opentelemetry-instrument` (AWS's distribution, `CLAIMSENSE_OTEL=1`) | CloudWatch: AgentCore Observability (GenAI Observability) and the `aws/spans` log group; needs Transaction Search on |
| Run metrics: duration, cost, tokens, resolutions, failures, fallbacks, outcomes | `agent/src/claimsense_agent/metrics.py`, after each run on AgentCore (`CLAIMSENSE_METRICS=1`) | CloudWatch metrics, namespace `ClaimSense`, dimension `Brain` |
| Evaluation pass rate | the evaluation, after a full run: CI on main (mock) and `make golden` with `CLAIMSENSE_METRICS=1` (Claude) | `ClaimSense/EvalPassRate` |
| Lambda duration, errors, throttles | Lambda itself | `AWS/Lambda` |

A **resolution** is a run that writes a note; cost per resolution = sum of `RunCostUsd` ÷ sum of
`Resolutions`.

## Dashboards (`dashboards/*.json`)

- **ClaimSense-Experience**: run duration p50/p95, runs and failures, Lambda p95, errors, throttles.
- **ClaimSense-Economics**: cost, resolutions and cost per resolution (last 24 h and hourly), tokens.
- **ClaimSense-Quality**: evaluation pass rate (mock and Claude, 90% gate line), live fallback and
  failure rates, decisions by outcome. The live rates are the continuous evaluation: every run's
  draft is checked by code, and a rising fallback rate is a quality regression.

## Alarms (`alarms/*.json`)

- **ClaimSense-SlowRuns**: p95 run duration over 2 minutes for 15 minutes.
- **ClaimSense-BadRuns**: over 25% of an hour's runs failed or fell back to code's decision.

No notification yet: the alarm state shows in CloudWatch. An SNS e-mail can be added.

## Set up

```bash
AWS_PROFILE=claimsense deploy/observability/setup.sh     # dashboards and alarms
AWS_PROFILE=claimsense deploy/agentcore/deploy.sh        # runtime with metrics and traces on
```

One-time, as root: CloudWatch → Settings → **Transaction Search** → Enable (spans to `aws/spans`).

## IAM

- Runtime role `claimsense-agentcore`: `cloudwatch:PutMetricData` for namespaces `bedrock-agentcore`
  and `ClaimSense` (`deploy/agentcore/iam/runtime-role-policy.json`).
- CI role `claimsense-github-ci`: inline policy `eval-metrics`, PutMetricData for `ClaimSense`
  (`deploy/ci/setup_github_oidc.sh`).
- IAM user: managed policy `ClaimSenseObservability` (`iam/deployer-policy.json`): dashboards and
  alarms named `ClaimSense-*`, read metrics, publish to `ClaimSense`, query the trace logs.
