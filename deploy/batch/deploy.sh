#!/usr/bin/env bash
# Deploy (or update) the scheduled batch assessment (decided 2026-11-04):
#   * the database change on the EC2 instance (the batch account, change detection; safe to re-run)
#   * the Lambda function claimsense-batch (no VPC: it calls the Claims API URL and AgentCore)
#   * the EventBridge Scheduler schedule claimsense-batch-every-4h
#
#   AWS_PROFILE=claimsense deploy/batch/deploy.sh
#   SCHEDULE_STATE=DISABLED AWS_PROFILE=claimsense deploy/batch/deploy.sh    # deploy, but paused
#
# Needs: the EC2 instance running, deploy/lambda/deploy.sh and deploy/agentcore/deploy.sh done, the
# roles claimsense-batch-lambda and claimsense-batch-scheduler and the ClaimSenseBatchDeploy rights
# (see README.md). The schedule does not run anything at deploy time; the first batch starts at the
# next 4-hour mark. To run one now: aws lambda invoke --function-name claimsense-batch --invocation-type Event /dev/null
set -euo pipefail
cd "$(dirname "$0")"

export AWS_REGION="${AWS_REGION:-us-east-1}"
FUNCTION="claimsense-batch"
SCHEDULE="claimsense-batch-every-4h"
SCHEDULE_STATE="${SCHEDULE_STATE:-ENABLED}"
MAX_CLAIMS="${BATCH_MAX_CLAIMS:-25}"
BUDGET="${BATCH_DAILY_BUDGET_USD:-5}"
PARALLEL="${BATCH_PARALLEL:-3}"
KEY_FILE="$HOME/.ssh/claimsense-key.pem"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
echo "==> account $ACCOUNT, region $AWS_REGION"

echo "==> the EC2 instance"
DNS=$(aws ec2 describe-instances \
  --filters Name=tag:Project,Values=claimsense Name=instance-state-name,Values=running \
  --query 'Reservations[0].Instances[0].PublicDnsName' --output text)
if [ "$DNS" = "None" ] || [ -z "$DNS" ]; then
  echo "No running ClaimSense instance: start it first." >&2
  exit 1
fi
SSH=(ssh -i "$KEY_FILE" -o StrictHostKeyChecking=accept-new "ec2-user@$DNS")
JWT_SECRET=$("${SSH[@]}" "sed -n 's/^CLAIMSENSE_JWT_SECRET=//p' /opt/claimsense/.env")

echo "==> database: batch account and change detection"
"${SSH[@]}" "cd /opt/claimsense && docker compose exec -T db psql -q -U claimsense -d claimsense -v ON_ERROR_STOP=1" \
  < ../../platform/db/migrations/2026-11-05_batch_assessment.sql
echo "    done"

API_URL=$(aws lambda get-function-url-config --function-name claimsense-api --query FunctionUrl --output text)
API_URL="${API_URL%/}"
RUNTIME_ARN=$(aws bedrock-agentcore-control list-agent-runtimes \
  --query "agentRuntimes[?agentRuntimeName=='claimsense_runner'].agentRuntimeArn | [0]" --output text)
echo "    Claims API $API_URL"
echo "    AgentCore runtime $RUNTIME_ARN"

echo "==> package (Linux x86_64, Python 3.12)"
rm -rf .build && mkdir -p .build/pkg
(cd ../../batch && uv export --frozen --no-dev --no-hashes --no-emit-project -q -o ../deploy/batch/.build/requirements.txt)
uv pip install -q --target .build/pkg -r .build/requirements.txt \
  --python-platform x86_64-manylinux2014 --python-version 3.12 --only-binary :all:
cp -r ../../batch/src/claimsense_batch .build/pkg/
find .build/pkg -name __pycache__ -type d -prune -exec rm -rf {} +
(cd .build/pkg && zip -q -r ../claimsense_batch.zip .)
echo "    claimsense_batch.zip: $(du -h .build/claimsense_batch.zip | cut -f1)"

ENVIRONMENT="Variables={CLAIMS_API_URL=$API_URL,AGENTCORE_RUNTIME_ARN=$RUNTIME_ARN,CLAIMSENSE_JWT_SECRET=$JWT_SECRET,BATCH_MAX_CLAIMS=$MAX_CLAIMS,BATCH_DAILY_BUDGET_USD=$BUDGET,BATCH_PARALLEL=$PARALLEL,CLAIMSENSE_METRICS=1}"

echo "==> function $FUNCTION"
if aws lambda get-function --function-name "$FUNCTION" >/dev/null 2>&1; then
  aws lambda update-function-code --function-name "$FUNCTION" --zip-file fileb://.build/claimsense_batch.zip >/dev/null
  aws lambda wait function-updated-v2 --function-name "$FUNCTION"
  aws lambda update-function-configuration --function-name "$FUNCTION" --environment "$ENVIRONMENT" >/dev/null
  echo "    updated"
else
  aws lambda create-function --function-name "$FUNCTION" \
    --runtime python3.12 --architectures x86_64 --handler claimsense_batch.handler.handler \
    --role "arn:aws:iam::$ACCOUNT:role/claimsense-batch-lambda" \
    --zip-file fileb://.build/claimsense_batch.zip --timeout 900 --memory-size 256 \
    --environment "$ENVIRONMENT" --tags Project=claimsense >/dev/null
  echo "    created"
fi
aws lambda wait function-updated-v2 --function-name "$FUNCTION"
FUNCTION_ARN=$(aws lambda get-function --function-name "$FUNCTION" --query Configuration.FunctionArn --output text)

echo "==> schedule $SCHEDULE (rate 4 hours, $SCHEDULE_STATE)"
TARGET="{\"Arn\":\"$FUNCTION_ARN\",\"RoleArn\":\"arn:aws:iam::$ACCOUNT:role/claimsense-batch-scheduler\",\"RetryPolicy\":{\"MaximumRetryAttempts\":0}}"
if aws scheduler get-schedule --name "$SCHEDULE" >/dev/null 2>&1; then
  ACTION=update-schedule
else
  ACTION=create-schedule
fi
# No retries: a batch that failed half-way is picked up by the next one, and a retry could run a
# claim twice.
aws scheduler "$ACTION" --name "$SCHEDULE" --schedule-expression "rate(4 hours)" \
  --flexible-time-window Mode=OFF --state "$SCHEDULE_STATE" --target "$TARGET" >/dev/null
echo "    $ACTION done"
echo "==> done. Logs: /aws/lambda/$FUNCTION. Run one batch now (in the background): aws lambda invoke --function-name $FUNCTION --invocation-type Event /dev/null"
