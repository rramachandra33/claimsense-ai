#!/usr/bin/env bash
# Create or update the three ClaimSense dashboards and the two alarms in CloudWatch. Safe to re-run.
#
#   AWS_PROFILE=claimsense deploy/observability/setup.sh
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

echo "==> alarms"
for file in alarms/*.json; do
  aws cloudwatch put-metric-alarm --cli-input-json "file://$file"
  echo "    $(basename "$file" .json)"
done
aws cloudwatch describe-alarms --alarm-name-prefix ClaimSense- \
  --query 'MetricAlarms[].[AlarmName,StateValue]' --output text
