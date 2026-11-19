# Incident report: invalid model id on AgentCore (drill)

**Date** 19 Nov 2026 · **Type** deliberate regression (incident drill, Milestone 5) · **Severity**
every assessment failed; no wrong decision reached a claim · **Status** resolved

**Time to verified recovery: 3 min 12 s** from the bad build going live (14:22:43 UTC) to two
correct assessments on the rolled-back build (14:25:55 UTC). Detection took 1 min 46 s; rollback
16 s.

## What happened

A one-character change to the Sonnet model id (`claude-sonnet-4-5-20250929-v1:0` → `…-v9:0`,
commit `9eecdc2`) was pushed to `main`. **CI passed it**: 150/150 on the evaluation gate, because
the gate runs the mock brain, which never calls Bedrock. CI pushed the images, and the build was
deployed to the AgentCore runtime `claimsense_runner`. On AgentCore the coverage agent's model
call failed ("The provided model identifier is invalid"), so every run ended with code's
agent-failure DENY: a draft for an adjuster, with no citation and the error as its reason.

## Timeline (UTC)

| Time | Event |
|---|---|
| 14:08–14:09 | Baseline on `bf35fd9` (last green CI): notes 15 (FLAG) and 16 (APPROVE), both drafted by the model |
| 14:10:14 | Regression `9eecdc2` pushed |
| 14:22:12 | CI green on `9eecdc2` (gate 150/150 on the mock); images pushed |
| **14:22:43** | **Bad build live on AgentCore** (`TAG=9eecdc2 deploy/agentcore/deploy.sh`) |
| 14:22:48–14:24:10 | Four assessments (claims 2238, 2019, 2165, 2311): all `agent_failure` DENY, notes 17–20 |
| **14:24:29** | **Alarm `ClaimSense-BadRuns` → ALARM**: bad-run rate 50% in the hour (threshold 25%) |
| 14:24:36 | Rollback started: runbook procedure 2, step 3 (`TAG=bf35fd9 deploy/agentcore/deploy.sh`) |
| 14:24:52 | AgentCore READY on `bf35fd9` |
| **14:25:55** | **Recovery verified**: CLM-2024-2165 APPROVE (note 21) and CLM-2024-2238 DENY (note 22), both `model`, no problems |
| after | Fix forward: `git revert` as `d08d6f0`, pushed; CI runs the gate again |

## Impact

* 4 runs failed; 4 agent-failure DENY drafts written (notes 17–20). They are drafts: nothing was
  paid, closed or denied to a customer, and the review rules require a reason before an adjuster
  can confirm or reject an agent-failure DENY. To be rejected in the console with the reason
  "incident drill".
* No data exposure; access control, audit and the draft checks were unaffected.
* Cost of the drill: about $0.30 in model calls.
* The runs were started as the `claimsense-batch` service account from the instance (people's
  development tokens are off on AWS). The scheduled batch itself stayed disabled.

## Detection

The alarm worked: it fired 1 min 46 s after the bad build went live, on the second bad run.
Two things limit it: it needs runs to happen (no traffic, no alarm), and it measures a one-hour
window, so after recovery it stays in ALARM until the bad runs leave the window (about an hour)
even though the service is healthy. Recovery was therefore verified by real runs, not by the
alarm returning to OK.

## Root cause and why the gate missed it

The model id lives in code (`agents/bedrock.py`) and is only exercised by a real Bedrock call.
The CI gate deliberately runs the mock brain (free, no AWS), and the Claude run (`make golden`) is
manual and was not run on this commit. So a change that breaks only the live model call passes CI.

## What we keep and what we change

**Worked:** images tagged by commit made the rollback one command (16 s); the agent-failure path
wrote a safe, reviewable draft instead of crashing or approving; the alarm fired within two minutes.

**Actions**

1. **Smoke test after every AgentCore deploy** (`deploy/agentcore/deploy.sh`): run one assessment
   on a fixed claim and roll back automatically if it ends in `agent_failure`. **Done the same
   day**: a dry run (no note written, no metrics) on CLM-2024-2165; on failure the previous image
   is deployed again and the script exits with an error.
2. **Check the model ids before deploying**: the deploy script calls Bedrock (`get-inference-profile`)
   for each id in `MODELS` and stops if one does not exist.
3. **Run the Claude evaluation on changes to the agents** (`agent/src/claimsense_agent/agents/`),
   at least the 20 baseline cases (about $1.40), before the images are deployed.
4. **Alarm on agent failures alone** over 5 minutes, so it fires on the first failures and clears
   soon after recovery; keep the hourly rate alarm for slower drift.
5. Grant `cloudwatch:DescribeAlarmHistory` to the operator so alarm transitions can be read back.
