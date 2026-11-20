#!/usr/bin/env bash
# Deploy (or update) ClaimSense on the EC2 instance: copy the Compose file, pull the images CI
# pushed to ECR, and (re)start the stack. Safe to re-run.
#
#   AWS_PROFILE=claimsense deploy/ec2/deploy.sh            # images tagged latest
#   TAG=<git sha> BRAIN=bedrock deploy/ec2/deploy.sh        # a specific build, Claude agents
#
# The JWT secret and the database password are generated on the instance the first time and stay
# there (/opt/claimsense/.env). deploy/lambda/deploy.sh reads them from there.
set -euo pipefail
cd "$(dirname "$0")"

export AWS_REGION="${AWS_REGION:-us-east-1}"
KEY_FILE="$HOME/.ssh/claimsense-key.pem"
TAG="${TAG:-latest}"
BRAIN="${BRAIN:-mock}"

ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGISTRY="$ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com"
DNS=$(aws ec2 describe-instances \
  --filters Name=tag:Project,Values=claimsense Name=instance-state-name,Values=running \
  --query 'Reservations[0].Instances[0].PublicDnsName' --output text)
if [ "$DNS" = "None" ] || [ -z "$DNS" ]; then
  echo "No running ClaimSense instance. Create or start it first (create_instance.sh)." >&2
  exit 1
fi
SSH=(ssh -i "$KEY_FILE" -o StrictHostKeyChecking=accept-new "ec2-user@$DNS")
echo "==> $DNS (images $REGISTRY/claimsense-*:$TAG, brain $BRAIN)"

echo "==> waiting for first-boot setup"
until "${SSH[@]}" test -f /opt/claimsense/.bootstrapped 2>/dev/null; do sleep 10; done

echo "==> copying the Compose file"
scp -i "$KEY_FILE" -q docker-compose.ec2.yml "ec2-user@$DNS:/opt/claimsense/docker-compose.yml"
scp -i "$KEY_FILE" -q Caddyfile "ec2-user@$DNS:/opt/claimsense/Caddyfile"

echo "==> pulling and starting the stack"
"${SSH[@]}" bash -s -- "$REGISTRY" "$TAG" "$BRAIN" "$AWS_REGION" <<'REMOTE'
set -euo pipefail
REGISTRY=$1 TAG=$2 BRAIN=$3 REGION=$4
cd /opt/claimsense
touch .env && chmod 600 .env
if ! grep -q '^CLAIMSENSE_JWT_SECRET=' .env; then
  echo "CLAIMSENSE_JWT_SECRET=$(openssl rand -hex 32)" >> .env
fi
if ! grep -q '^CLAIMSENSE_DB_PASSWORD=' .env; then
  PASSWORD=$(openssl rand -hex 24)
  echo "CLAIMSENSE_DB_PASSWORD=$PASSWORD" >> .env
  # A database created earlier still has the old password: change it in place.
  if docker compose ps --status running --services 2>/dev/null | grep -qx db; then
    # </dev/null: this script arrives on stdin, and psql would otherwise read the rest of it.
    docker compose exec -T db psql -q -U claimsense -c "ALTER USER claimsense PASSWORD '$PASSWORD'" </dev/null
  fi
fi
# Settings that follow each deploy; the secret line stays.
grep -v -E '^(REGISTRY|TAG|BRAIN)=' .env > .env.new || true
printf 'REGISTRY=%s\nTAG=%s\nBRAIN=%s\n' "$REGISTRY" "$TAG" "$BRAIN" >> .env.new
mv .env.new .env && chmod 600 .env
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY" >/dev/null
docker compose pull --quiet
docker compose up -d --wait
docker compose ps --format '{{.Service}}: {{.Status}}'
REMOTE

echo "==> ready: http://$DNS:3100"
