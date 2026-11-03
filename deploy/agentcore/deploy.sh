#!/usr/bin/env bash
# Deploy (or update) the runner on Amazon Bedrock AgentCore Runtime as claimsense_runner, from the
# arm64 runner image CI pushed to ECR (claimsense-runner:arm64-<tag>). Then switch the console's
# Run assessment to it: the runner on the EC2 instance forwards each run there. Safe to re-run.
#
#   AWS_PROFILE=claimsense deploy/agentcore/deploy.sh             # arm64-latest, Claude agents
#   TAG=<git sha> BRAIN=mock deploy/agentcore/deploy.sh
#
# Needs: deploy/lambda/deploy.sh done (the agents call those two functions), the role
# claimsense-agentcore and the ClaimSenseAgentCoreDeploy rights (see README.md).
set -euo pipefail
cd "$(dirname "$0")"

export AWS_REGION="${AWS_REGION:-us-east-1}"
NAME="claimsense_runner"
TAG="${TAG:-latest}"
BRAIN="${BRAIN:-bedrock}"
KEY_FILE="$HOME/.ssh/claimsense-key.pem"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
IMAGE="$ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com/claimsense-runner:arm64-$TAG"
ROLE_ARN="arn:aws:iam::$ACCOUNT:role/claimsense-agentcore"

API_URL=$(aws lambda get-function-url-config --function-name claimsense-api --query FunctionUrl --output text)
MCP_URL=$(aws lambda get-function-url-config --function-name claimsense-mcp --query FunctionUrl --output text)
API_URL="${API_URL%/}"
MCP_URL="${MCP_URL%/}"
echo "==> image $IMAGE, brain $BRAIN"
echo "    Claims API $API_URL"
echo "    MCP registry $MCP_URL/registry/v0/servers"

ARTIFACT="{\"containerConfiguration\":{\"containerUri\":\"$IMAGE\"}}"
NETWORK='{"networkMode":"PUBLIC"}'
ENVIRONMENT="{\"RUNNER_PORT\":\"8080\",\"CLAIMSENSE_BRAIN\":\"$BRAIN\",\"CLAIMSENSE_API_URL\":\"$API_URL\",\"CLAIMSENSE_MCP_REGISTRY_URL\":\"$MCP_URL/registry/v0/servers\",\"AWS_DEFAULT_REGION\":\"$AWS_REGION\"}"

echo "==> runtime $NAME"
RUNTIME_ID=$(aws bedrock-agentcore-control list-agent-runtimes \
  --query "agentRuntimes[?agentRuntimeName=='$NAME'].agentRuntimeId | [0]" --output text)
if [ "$RUNTIME_ID" = "None" ] || [ -z "$RUNTIME_ID" ]; then
  RUNTIME_ID=$(aws bedrock-agentcore-control create-agent-runtime --agent-runtime-name "$NAME" \
    --description "ClaimSense runner: four agents, one claim per invocation" \
    --agent-runtime-artifact "$ARTIFACT" --role-arn "$ROLE_ARN" \
    --network-configuration "$NETWORK" --environment-variables "$ENVIRONMENT" \
    --tags Project=claimsense --query agentRuntimeId --output text)
  echo "    created $RUNTIME_ID"
else
  # Each update makes a new immutable version; the DEFAULT endpoint moves to it.
  aws bedrock-agentcore-control update-agent-runtime --agent-runtime-id "$RUNTIME_ID" \
    --agent-runtime-artifact "$ARTIFACT" --role-arn "$ROLE_ARN" \
    --network-configuration "$NETWORK" --environment-variables "$ENVIRONMENT" >/dev/null
  echo "    updated $RUNTIME_ID"
fi

echo "==> waiting until it is READY"
for _ in $(seq 1 60); do
  STATUS=$(aws bedrock-agentcore-control get-agent-runtime --agent-runtime-id "$RUNTIME_ID" \
    --query status --output text)
  case "$STATUS" in
    READY) break ;;
    *FAILED*) echo "    $STATUS:"; aws bedrock-agentcore-control get-agent-runtime \
                --agent-runtime-id "$RUNTIME_ID" --query failureReason --output text; exit 1 ;;
  esac
  sleep 10
done
RUNTIME_ARN=$(aws bedrock-agentcore-control get-agent-runtime --agent-runtime-id "$RUNTIME_ID" \
  --query agentRuntimeArn --output text)
echo "    $STATUS: $RUNTIME_ARN"

echo "==> console's Run assessment → AgentCore (the runner on the instance forwards)"
DNS=$(aws ec2 describe-instances \
  --filters Name=tag:Project,Values=claimsense Name=instance-state-name,Values=running \
  --query 'Reservations[0].Instances[0].PublicDnsName' --output text)
ssh -i "$KEY_FILE" -o StrictHostKeyChecking=accept-new "ec2-user@$DNS" bash -s -- "$RUNTIME_ARN" <<'REMOTE'
set -euo pipefail
cd /opt/claimsense
grep -v '^AGENTCORE_RUNTIME_ARN=' .env > .env.new || true
echo "AGENTCORE_RUNTIME_ARN=$1" >> .env.new
mv .env.new .env && chmod 600 .env
docker compose up -d --wait --no-deps runner
curl -s localhost:8100/health
REMOTE
echo
echo "==> done"
