# The scheduled batch assessment

Every 4 hours, ClaimSense assesses the open claims that need it, so adjusters do not have to click
Run assessment themselves (decided 2026-11-04, see DECISIONS.md).

```
EventBridge Scheduler (rate 4 hours) ──> Lambda claimsense-batch
    1. signs a 1-hour token for the claimsense-batch service account
    2. GET  claimsense-api /api/v1/batch/candidates  → open claims never assessed, or whose
                                                       documents changed; today's batch spend
    3. InvokeAgentRuntime claimsense_runner, 3 at a time → four agents → draft note
    4. CloudWatch ClaimSense: BatchClaimsPicked, BatchRuns, BatchFailures, BatchCostUsd
```

- **Which claims**: Pending Review, Under Investigation and Escalated claims that were never
  assessed, or whose documents changed since their last assessment. A change is a different
  fingerprint of the claim's documents (id, OCR status, hash of the text), stored on each assessment.
- **Who it acts as**: the `claimsense-batch` service account (group `batch-service`). The API lets it
  read open claims only; it cannot sign in to the console or confirm anything. Its notes are drafts
  for the claim's **assigned adjuster** ("by the scheduled batch" in the console); the audit log
  records the batch account.
- **Limits**: at most 25 claims a batch, $5 a day (today's spend comes from the cost recorded on
  each batch assessment), and it stops starting runs with less than 4 minutes left of the Lambda's
  15. A failed claim does not stop the batch; it is picked up by the next one. No retries.
- The code: `batch/` (the Lambda), `api/src/claimsense_api/batch.py` (the candidates),
  migration `platform/db/migrations/2026-11-05_batch_assessment.sql`.

## Deploy

```bash
AWS_PROFILE=claimsense deploy/batch/deploy.sh                          # schedule on
SCHEDULE_STATE=DISABLED AWS_PROFILE=claimsense deploy/batch/deploy.sh  # deployed, paused
aws lambda invoke --function-name claimsense-batch --invocation-type Event /dev/null --profile claimsense
                                                                       # one batch now
```

Needs the EC2 instance running (the script reads the token secret there and applies the database
change), and the two functions and the AgentCore runtime deployed.

## One-time IAM set-up (as root, in the console; replace `ACCOUNT` with the account id)

1. **Role `claimsense-batch-lambda`**: IAM → Roles → Create role → Custom trust policy
   `iam/batch-role-trust.json` (Lambda) → no managed policy → name it → then add the inline policy
   `iam/batch-role-policy.json` (name `ClaimSenseBatch`): its own logs, InvokeAgentRuntime on
   `claimsense_runner-*`, and metrics in the `ClaimSense` namespace only.
2. **Role `claimsense-batch-scheduler`**: Create role → Custom trust policy
   `iam/scheduler-role-trust.json` (EventBridge Scheduler, this account only) → inline policy
   `iam/scheduler-role-policy.json` (name `StartTheBatch`): invoke `claimsense-batch` only.
3. **Managed policy `ClaimSenseBatchDeploy`** from `iam/deployer-policy.json`, attached to the IAM
   user `rramachandra33`: manage the `claimsense-*` schedules and pass only these two roles.
   Creating and updating the function itself is already allowed by `ClaimSenseLambdaDeploy`
   (`function:claimsense-*`).
