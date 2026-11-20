#!/usr/bin/env bash
# Create or update the three ClaimSense dashboards and the two alarms in CloudWatch, the alarm
# topic, and the log retention. Safe to re-run.
#
#   AWS_PROFILE=claimsense ALARM_EMAIL=you@example.com deploy/observability/setup.sh
#
# ALARM_EMAIL subscribes that address to the SNS topic claimsense-alarms (AWS sends a confirmation
# email; nothing is delivered until the link in it is clicked). Both alarms notify the topic when
# they go to ALARM and when they return to OK. Without ALARM_EMAIL the topic and the alarm actions
# are still set up. LOG_RETENTION_DAYS (default 90) is applied to the ClaimSense log groups
# (decided 2026-11-19, observation document §6).
#
# The metrics come from the runner on AgentCore (namespace ClaimSense, see
# agent/src/claimsense_agent/metrics.py), the Lambda functions (AWS/Lambda) and the evaluation.
set -euo pipefail
cd "$(dirname "$0")"
export AWS_REGION="${AWS_REGION:-us-east-1}"

echo "==> dashboards"
for file in dashboards/*.json; do
  name=$(basename "$file" .json)
  aws cloudwatch put-dashboard --dashboard-name "$name" --dashboard-body "file://$file" \
    --query 'DashboardValidationMessages' --output text
  echo "    $name: https://$AWS_REGION.console.aws.amazon.com/cloudwatch/home?region=$AWS_REGION#dashboards/dashboard/$name"
done

echo "==> alarm topic claimsense-alarms"
TOPIC_ARN=$(aws sns create-topic --name claimsense-alarms --tags Key=Project,Value=claimsense \
  --query TopicArn --output text)
echo "    $TOPIC_ARN"
if [ -n "${ALARM_EMAIL:-}" ]; then
  if aws sns list-subscriptions-by-topic --topic-arn "$TOPIC_ARN" \
       --query 'Subscriptions[].Endpoint' --output text | tr '\t' '\n' | grep -qx "$ALARM_EMAIL"; then
    echo "    $ALARM_EMAIL already subscribed (or awaiting confirmation)"
  else
    aws sns subscribe --topic-arn "$TOPIC_ARN" --protocol email --notification-endpoint "$ALARM_EMAIL" >/dev/null
    echo "    subscribed $ALARM_EMAIL: confirm the link in the email AWS sends"
  fi
fi

echo "==> alarms (notify the topic on ALARM and on OK)"
for file in alarms/*.json; do
  python3 -c '
import json, sys
alarm = json.load(open(sys.argv[1]))
alarm["AlarmActions"] = [sys.argv[2]]
alarm["OKActions"] = [sys.argv[2]]
alarm["ActionsEnabled"] = True
print(json.dumps(alarm))' "$file" "$TOPIC_ARN" > "/tmp/claimsense-alarm.json"
  aws cloudwatch put-metric-alarm --cli-input-json "file:///tmp/claimsense-alarm.json"
  echo "    $(basename "$file" .json)"
done
rm -f /tmp/claimsense-alarm.json

echo "==> log retention: ${LOG_RETENTION_DAYS:-90} days"
for prefix in /aws/lambda/claimsense- /aws/bedrock-agentcore/runtimes/claimsense_runner-; do
  for group in $(aws logs describe-log-groups --log-group-name-prefix "$prefix" \
                   --query 'logGroups[].logGroupName' --output text); do
    aws logs put-retention-policy --log-group-name "$group" --retention-in-days "${LOG_RETENTION_DAYS:-90}"
    echo "    $group"
  done
done
aws cloudwatch describe-alarms --alarm-name-prefix ClaimSense- \
  --query 'MetricAlarms[].[AlarmName,StateValue]' --output text
