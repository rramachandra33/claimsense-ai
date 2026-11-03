#!/usr/bin/env bash
# Deploy (or update) the Lambda Claims API: the data API (api/) as the function claimsense-api,
# with a Function URL, inside the default VPC so it can reach PostgreSQL on the EC2 instance.
# Then point the agents on the instance (MCP server and runner) at it. Safe to re-run.
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

echo "==> package (Linux x86_64, Python 3.12)"
rm -rf .build && mkdir -p .build/package
(cd ../../api && uv export --frozen --no-dev --no-hashes --no-emit-project -o ../deploy/lambda/.build/requirements.txt -q)
uv pip install -q --target .build/package -r .build/requirements.txt \
  --python-platform x86_64-manylinux2014 --python-version 3.12 --only-binary :all:
cp -r ../../api/src/claimsense_api .build/package/
find .build/package -name __pycache__ -type d -prune -exec rm -rf {} +
(cd .build/package && zip -q -r ../function.zip .)
echo "    $(du -h .build/function.zip | cut -f1)"

ENVIRONMENT="Variables={CLAIMSENSE_DB_URL=postgresql://claimsense:$DB_PASSWORD@$PRIVATE_IP:5432/claimsense,CLAIMSENSE_JWT_SECRET=$JWT_SECRET,CLAIMSENSE_RATE_LIMIT_PER_MINUTE=$RATE_LIMIT}"
SUBNETS=$(aws ec2 describe-subnets --filters Name=vpc-id,Values="$VPC" Name=default-for-az,Values=true \
  --query 'Subnets[].SubnetId' --output text | tr '\t' ',')

echo "==> function $FUNCTION"
if aws lambda get-function --function-name "$FUNCTION" >/dev/null 2>&1; then
  aws lambda update-function-code --function-name "$FUNCTION" --zip-file fileb://.build/function.zip >/dev/null
  aws lambda wait function-updated-v2 --function-name "$FUNCTION"
  aws lambda update-function-configuration --function-name "$FUNCTION" --environment "$ENVIRONMENT" \
    --vpc-config "SubnetIds=$SUBNETS,SecurityGroupIds=$LAMBDA_SG" >/dev/null
  echo "    updated"
else
  aws lambda create-function --function-name "$FUNCTION" \
    --runtime python3.12 --architectures x86_64 \
    --handler claimsense_api.lambda_handler.handler \
    --role "arn:aws:iam::$ACCOUNT:role/claimsense-lambda-api" \
    --zip-file fileb://.build/function.zip \
    --timeout 30 --memory-size 512 \
    --environment "$ENVIRONMENT" \
    --vpc-config "SubnetIds=$SUBNETS,SecurityGroupIds=$LAMBDA_SG" \
    --tags Project=claimsense >/dev/null
  echo "    created (attaching to the VPC takes a minute)"
fi
aws lambda wait function-updated-v2 --function-name "$FUNCTION"

echo "==> Function URL"
URL=$(aws lambda get-function-url-config --function-name "$FUNCTION" --query FunctionUrl --output text 2>/dev/null || true)
if [ -z "$URL" ]; then
  URL=$(aws lambda create-function-url-config --function-name "$FUNCTION" --auth-type NONE \
    --query FunctionUrl --output text)
  # Auth type NONE: anyone may call the URL; the app's token check decides what they get.
  aws lambda add-permission --function-name "$FUNCTION" --statement-id public-url \
    --action lambda:InvokeFunctionUrl --principal "*" --function-url-auth-type NONE >/dev/null
  aws lambda add-permission --function-name "$FUNCTION" --statement-id public-url-invoke \
    --action lambda:InvokeFunction --principal "*" --invoked-via-function-url >/dev/null 2>&1 || true
fi
URL="${URL%/}"
echo "    $URL"

echo "==> checks"
curl -fsS "$URL/api/v1/health" && echo
STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$URL/api/v1/dev/login" \
  -H 'content-type: application/json' -d '{"user_id":"alice"}')
echo "    development sign-in on the public URL: HTTP $STATUS (expected 404)"

echo "==> pointing the agents on the instance at the Lambda Claims API"
"${SSH[@]}" bash -s -- "$URL" <<'REMOTE'
set -euo pipefail
cd /opt/claimsense
grep -v '^CLAIMS_API_URL=' .env > .env.new || true
echo "CLAIMS_API_URL=$1" >> .env.new
mv .env.new .env && chmod 600 .env
docker compose up -d --wait --no-deps mcp runner     # no-deps: do not re-run the seed job
docker compose ps --format '{{.Service}}: {{.Status}}'
REMOTE
echo "==> done: Claims API $URL"
