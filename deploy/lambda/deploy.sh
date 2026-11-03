#!/usr/bin/env bash
# Deploy (or update) the two Lambda functions, each with a Function URL:
#   claimsense-api  the data API (api/), inside the default VPC so it can reach PostgreSQL on EC2
#   claimsense-mcp  the MCP server and its registry (mcp_server/), calling claimsense-api
# Then point the agents on the instance (MCP server and runner) at them. Safe to re-run.
#
#   AWS_PROFILE=claimsense deploy/lambda/deploy.sh
#
# Needs: the EC2 instance deployed (deploy/ec2/deploy.sh), the role claimsense-lambda-api and the
# ClaimSenseLambdaDeploy rights (see README.md).
#
# The function runs with the development sign-in OFF: its URL is public, and only requests with a
# valid token get past the token check. Sign-in stays on the instance's private API until Cognito.
set -euo pipefail
cd "$(dirname "$0")"

export AWS_REGION="${AWS_REGION:-us-east-1}"
FUNCTION="claimsense-api"
MCP_FUNCTION="claimsense-mcp"
LAMBDA_SG_NAME="claimsense-lambda-sg"
TAGS="{Key=Project,Value=claimsense},{Key=Name,Value=$LAMBDA_SG_NAME}"
KEY_FILE="$HOME/.ssh/claimsense-key.pem"
RATE_LIMIT="${RATE_LIMIT:-300}"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
echo "==> account $ACCOUNT, region $AWS_REGION"

echo "==> the EC2 instance"
read -r INSTANCE PRIVATE_IP DNS EC2_SG VPC < <(aws ec2 describe-instances \
  --filters Name=tag:Project,Values=claimsense Name=instance-state-name,Values=running \
  --query 'Reservations[0].Instances[0].[InstanceId,PrivateIpAddress,PublicDnsName,SecurityGroups[0].GroupId,VpcId]' \
  --output text)
if [ "$INSTANCE" = "None" ]; then
  echo "No running ClaimSense instance. Start it and run deploy/ec2/deploy.sh first." >&2
  exit 1
fi
SSH=(ssh -i "$KEY_FILE" -o StrictHostKeyChecking=accept-new "ec2-user@$DNS")
echo "    $INSTANCE, private IP $PRIVATE_IP"

# The secrets live on the instance; read them without printing them.
ENV_FILE=$("${SSH[@]}" cat /opt/claimsense/.env)
JWT_SECRET=$(printf '%s\n' "$ENV_FILE" | sed -n 's/^CLAIMSENSE_JWT_SECRET=//p')
DB_PASSWORD=$(printf '%s\n' "$ENV_FILE" | sed -n 's/^CLAIMSENSE_DB_PASSWORD=//p')
if [ -z "$JWT_SECRET" ] || [ -z "$DB_PASSWORD" ]; then
  echo "The instance has no JWT secret or database password yet: run deploy/ec2/deploy.sh first." >&2
  exit 1
fi

echo "==> security group $LAMBDA_SG_NAME (the Lambda's; no inbound rules)"
LAMBDA_SG=$(aws ec2 describe-security-groups --filters Name=group-name,Values="$LAMBDA_SG_NAME" Name=vpc-id,Values="$VPC" \
  --query 'SecurityGroups[0].GroupId' --output text)
if [ "$LAMBDA_SG" = "None" ]; then
  LAMBDA_SG=$(aws ec2 create-security-group --group-name "$LAMBDA_SG_NAME" --vpc-id "$VPC" \
    --description "ClaimSense Lambda Claims API" \
    --tag-specifications "ResourceType=security-group,Tags=[$TAGS]" --query GroupId --output text)
  echo "    created $LAMBDA_SG"
else
  echo "    already there: $LAMBDA_SG"
fi
echo "==> PostgreSQL on the instance: port 5432 from $LAMBDA_SG only"
if aws ec2 authorize-security-group-ingress --group-id "$EC2_SG" --protocol tcp --port 5432 \
     --source-group "$LAMBDA_SG" >/dev/null 2>&1; then
  echo "    rule added to $EC2_SG"
else
  echo "    rule already there"
fi

# package <project folder> <package name>: build .build/<package>.zip with Linux x86_64 wheels.
package() {
  local project=$1 name=$2 dir=".build/$2"
  rm -rf "$dir" && mkdir -p "$dir"
  (cd "../../$project" && uv export --frozen --no-dev --no-hashes --no-emit-project -q \
     -o "../deploy/lambda/.build/$name-requirements.txt")
  uv pip install -q --target "$dir" -r ".build/$name-requirements.txt" \
    --python-platform x86_64-manylinux2014 --python-version 3.12 --only-binary :all:
  cp -r "../../$project/src/$name" "$dir/"
  find "$dir" -name __pycache__ -type d -prune -exec rm -rf {} +
  rm -f ".build/$name.zip" && (cd "$dir" && zip -q -r "../$name.zip" .)
  echo "    $name.zip: $(du -h ".build/$name.zip" | cut -f1)"
}

# function_url <function>: the function's public URL (created on first use), without a trailing /.
function_url() {
  local fn=$1 url
  url=$(aws lambda get-function-url-config --function-name "$fn" --query FunctionUrl --output text 2>/dev/null || true)
  if [ -z "$url" ]; then
    url=$(aws lambda create-function-url-config --function-name "$fn" --auth-type NONE \
      --query FunctionUrl --output text)
    # Auth type NONE: anyone may call the URL; the app's token check decides what they get.
    aws lambda add-permission --function-name "$fn" --statement-id public-url \
      --action lambda:InvokeFunctionUrl --principal "*" --function-url-auth-type NONE >/dev/null
    aws lambda add-permission --function-name "$fn" --statement-id public-url-invoke \
      --action lambda:InvokeFunction --principal "*" --invoked-via-function-url >/dev/null 2>&1 || true
  fi
  echo "${url%/}"
}

# deploy_function <function> <zip> <handler> <environment> [vpc config]: create or update.
deploy_function() {
  local fn=$1 zip=$2 handler=$3 environment=$4 vpc=${5:-}
  local vpc_args=()
  if [ -n "$vpc" ]; then vpc_args=(--vpc-config "$vpc"); fi
  if aws lambda get-function --function-name "$fn" >/dev/null 2>&1; then
    aws lambda update-function-code --function-name "$fn" --zip-file "fileb://$zip" >/dev/null
    aws lambda wait function-updated-v2 --function-name "$fn"
    aws lambda update-function-configuration --function-name "$fn" --environment "$environment" \
      ${vpc_args[@]+"${vpc_args[@]}"} >/dev/null
    echo "    $fn updated"
  else
    aws lambda create-function --function-name "$fn" \
      --runtime python3.12 --architectures x86_64 --handler "$handler" \
      --role "arn:aws:iam::$ACCOUNT:role/claimsense-lambda-api" \
      --zip-file "fileb://$zip" --timeout 30 --memory-size 512 \
      --environment "$environment" ${vpc_args[@]+"${vpc_args[@]}"} --tags Project=claimsense >/dev/null
    echo "    $fn created"
  fi
  aws lambda wait function-updated-v2 --function-name "$fn"
}

echo "==> packages (Linux x86_64, Python 3.12)"
package api claimsense_api
package mcp_server claimsense_mcp

ENVIRONMENT="Variables={CLAIMSENSE_DB_URL=postgresql://claimsense:$DB_PASSWORD@$PRIVATE_IP:5432/claimsense,CLAIMSENSE_JWT_SECRET=$JWT_SECRET,CLAIMSENSE_RATE_LIMIT_PER_MINUTE=$RATE_LIMIT}"
SUBNETS=$(aws ec2 describe-subnets --filters Name=vpc-id,Values="$VPC" Name=default-for-az,Values=true \
  --query 'Subnets[].SubnetId' --output text | tr '\t' ',')

echo "==> function $FUNCTION (in the VPC; attaching to it takes a minute the first time)"
deploy_function "$FUNCTION" .build/claimsense_api.zip claimsense_api.lambda_handler.handler \
  "$ENVIRONMENT" "SubnetIds=$SUBNETS,SecurityGroupIds=$LAMBDA_SG"
URL=$(function_url "$FUNCTION")
echo "    $URL"

echo "==> function $MCP_FUNCTION (no VPC: it calls $FUNCTION over its URL)"
# The registry must give agents this function's own URL, which exists only once the function does.
MCP_URL=$(aws lambda get-function-url-config --function-name "$MCP_FUNCTION" --query FunctionUrl --output text 2>/dev/null || true)
MCP_ENVIRONMENT="Variables={CLAIMSENSE_API_URL=$URL,CLAIMSENSE_MCP_PUBLIC_URL=${MCP_URL%/}/mcp}"
deploy_function "$MCP_FUNCTION" .build/claimsense_mcp.zip claimsense_mcp.lambda_handler.handler "$MCP_ENVIRONMENT"
if [ -z "$MCP_URL" ]; then
  MCP_URL=$(function_url "$MCP_FUNCTION")
  aws lambda update-function-configuration --function-name "$MCP_FUNCTION" \
    --environment "Variables={CLAIMSENSE_API_URL=$URL,CLAIMSENSE_MCP_PUBLIC_URL=$MCP_URL/mcp}" >/dev/null
  aws lambda wait function-updated-v2 --function-name "$MCP_FUNCTION"
fi
MCP_URL="${MCP_URL%/}"
echo "    $MCP_URL"

echo "==> checks"
curl -fsS "$URL/api/v1/health" && echo
STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$URL/api/v1/dev/login" \
  -H 'content-type: application/json' -d '{"user_id":"alice"}')
echo "    development sign-in on the public URL: HTTP $STATUS (expected 404)"
curl -fsS "$MCP_URL/registry/v0/servers" && echo

echo "==> pointing the agents on the instance at the two functions"
"${SSH[@]}" bash -s -- "$URL" "$MCP_URL" <<'REMOTE'
set -euo pipefail
cd /opt/claimsense
grep -v -E '^(CLAIMS_API_URL|MCP_REGISTRY_URL)=' .env > .env.new || true
echo "CLAIMS_API_URL=$1" >> .env.new
echo "MCP_REGISTRY_URL=$2/registry/v0/servers" >> .env.new
mv .env.new .env && chmod 600 .env
docker compose up -d --wait --no-deps mcp runner     # no-deps: do not re-run the seed job
docker compose ps --format '{{.Service}}: {{.Status}}'
REMOTE
echo "==> done: Claims API $URL, MCP server and registry $MCP_URL"
