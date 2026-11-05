#!/usr/bin/env bash
# Amazon Cognito for the ClaimSense console (decided 2026-11-05). Safe to re-run.
#
#   AWS_PROFILE=claimsense deploy/cognito/setup.sh                    # pool, users; then EC2
#   RESET_PASSWORDS=1 AWS_PROFILE=claimsense deploy/cognito/setup.sh  # new passwords for everyone
#   SKIP_EC2=1 AWS_PROFILE=claimsense deploy/cognito/setup.sh         # pool and users only
#
# 1. User pool "claimsense-users": no self sign-up, no MFA (for now), passwords of 12+ characters
#    with upper case, lower case, a number and a symbol; deletion protection on.
# 2. App client "claimsense-console": no client secret, user name + password sign-in
#    (USER_PASSWORD_AUTH) from the console's server, access tokens valid 8 hours (the console's
#    session length), "user not found" reported the same as a wrong password.
# 3. The four groups (the roles) and the people in data/identity/users.json with one of them:
#    alice, david, bob, carol, eve, and frank (suspended in ClaimSense: Cognito lets him in, the
#    data API refuses him). Not the batch service account: it is not a person and never signs in.
#    New users get a generated permanent password, written to ~/.claimsense/cognito-test-users.txt
#    (readable by you only, never in the repository).
# 4. Unless SKIP_EC2=1: writes COGNITO_POOL_ID, COGNITO_CLIENT_ID and DEV_LOGIN=0 to the
#    instance's .env and restarts the api and web containers with the latest images. Then run
#    deploy/lambda/deploy.sh so the Lambda Claims API accepts Cognito tokens too.
#
# Needs: the managed policy ClaimSenseCognitoDeploy on the IAM user (iam/deployer-policy.json).
set -euo pipefail
cd "$(dirname "$0")"

export AWS_REGION="${AWS_REGION:-us-east-1}"
POOL_NAME="claimsense-users"
CLIENT_NAME="claimsense-console"
GROUPS_WITH_ROLES=(adjuster senior-adjuster fraud-investigator total-loss-appraiser)
PASSWORD_DIR="$HOME/.claimsense"
PASSWORD_FILE="$PASSWORD_DIR/cognito-test-users.txt"
KEY_FILE="$HOME/.ssh/claimsense-key.pem"

echo "==> account $(aws sts get-caller-identity --query Account --output text), region $AWS_REGION"

echo "==> user pool $POOL_NAME"
POOL_ID=$(aws cognito-idp list-user-pools --max-results 60 \
  --query "UserPools[?Name=='$POOL_NAME'].Id | [0]" --output text)
if [ "$POOL_ID" = "None" ] || [ -z "$POOL_ID" ]; then
  POOL_ID=$(aws cognito-idp create-user-pool --pool-name "$POOL_NAME" \
    --policies 'PasswordPolicy={MinimumLength=12,RequireUppercase=true,RequireLowercase=true,RequireNumbers=true,RequireSymbols=true,TemporaryPasswordValidityDays=1}' \
    --mfa-configuration OFF \
    --admin-create-user-config AllowAdminCreateUserOnly=true \
    --username-configuration CaseSensitive=false \
    --account-recovery-setting 'RecoveryMechanisms=[{Priority=1,Name=admin_only}]' \
    --deletion-protection ACTIVE \
    --user-pool-tags Project=claimsense \
    --query UserPool.Id --output text)
  echo "    created $POOL_ID"
else
  echo "    already there: $POOL_ID"
fi

echo "==> app client $CLIENT_NAME"
CLIENT_SETTINGS=(
  --explicit-auth-flows ALLOW_USER_PASSWORD_AUTH ALLOW_REFRESH_TOKEN_AUTH
  --access-token-validity 8 --id-token-validity 8 --refresh-token-validity 1
  --token-validity-units AccessToken=hours,IdToken=hours,RefreshToken=days
  --prevent-user-existence-errors ENABLED --enable-token-revocation
)
CLIENT_ID=$(aws cognito-idp list-user-pool-clients --user-pool-id "$POOL_ID" --max-results 60 \
  --query "UserPoolClients[?ClientName=='$CLIENT_NAME'].ClientId | [0]" --output text)
if [ "$CLIENT_ID" = "None" ] || [ -z "$CLIENT_ID" ]; then
  CLIENT_ID=$(aws cognito-idp create-user-pool-client --user-pool-id "$POOL_ID" \
    --client-name "$CLIENT_NAME" --no-generate-secret "${CLIENT_SETTINGS[@]}" \
    --query UserPoolClient.ClientId --output text)
  echo "    created $CLIENT_ID"
else
  # An update resets every setting it is not given, so it is given all of them again.
  aws cognito-idp update-user-pool-client --user-pool-id "$POOL_ID" --client-id "$CLIENT_ID" \
    --client-name "$CLIENT_NAME" "${CLIENT_SETTINGS[@]}" >/dev/null
  echo "    already there: $CLIENT_ID (settings refreshed)"
fi

echo "==> groups"
for group in "${GROUPS_WITH_ROLES[@]}"; do
  if aws cognito-idp get-group --user-pool-id "$POOL_ID" --group-name "$group" >/dev/null 2>&1; then
    echo "    $group (already there)"
  else
    aws cognito-idp create-group --user-pool-id "$POOL_ID" --group-name "$group" \
      --description "ClaimSense role $group (data/identity/users.json)" >/dev/null
    echo "    $group (created)"
  fi
done

# A password Cognito's policy accepts: 16 random letters and digits, then one of each kind.
new_password() {
  printf '%s-Aa7\n' "$(openssl rand -base64 24 | tr -dc 'A-Za-z0-9' | cut -c1-16)"
}

echo "==> users (from data/identity/users.json)"
mkdir -p "$PASSWORD_DIR" && chmod 700 "$PASSWORD_DIR"
touch "$PASSWORD_FILE" && chmod 600 "$PASSWORD_FILE"
USERS=$(python3 -c '
import json, sys
roles = set(sys.argv[2:])
for user in json.load(open(sys.argv[1]))["users"]:
    if user["group"] in roles:
        print(user["user_id"], user["group"], user["name"].replace(" ", "_"))
' ../../data/identity/users.json "${GROUPS_WITH_ROLES[@]}")
while read -r user group name <&3; do        # fd 3: the aws calls inside may read stdin
  name=${name//_/ }
  set_password=no
  if aws cognito-idp admin-get-user --user-pool-id "$POOL_ID" --username "$user" >/dev/null 2>&1; then
    state="already there"
    if [ "${RESET_PASSWORDS:-0}" = "1" ]; then set_password=yes; fi
  else
    aws cognito-idp admin-create-user --user-pool-id "$POOL_ID" --username "$user" \
      --user-attributes Name=name,Value="$name" --message-action SUPPRESS >/dev/null
    state="created"
    set_password=yes
  fi
  if [ "$set_password" = "yes" ]; then
    password=$(new_password)
    aws cognito-idp admin-set-user-password --user-pool-id "$POOL_ID" --username "$user" \
      --password "$password" --permanent
    grep -v "^$user " "$PASSWORD_FILE" > "$PASSWORD_FILE.new" || true
    echo "$user $password" >> "$PASSWORD_FILE.new"
    mv "$PASSWORD_FILE.new" "$PASSWORD_FILE" && chmod 600 "$PASSWORD_FILE"
    state="$state, password set"
  fi
  # Exactly one group: the role in users.json.
  for current in $(aws cognito-idp admin-list-groups-for-user --user-pool-id "$POOL_ID" --username "$user" \
                     --query 'Groups[].GroupName' --output text); do
    if [ "$current" != "$group" ]; then
      aws cognito-idp admin-remove-user-from-group --user-pool-id "$POOL_ID" --username "$user" --group-name "$current"
    fi
  done
  aws cognito-idp admin-add-user-to-group --user-pool-id "$POOL_ID" --username "$user" --group-name "$group"
  echo "    $user ($group): $state"
done 3<<< "$USERS"
echo "    passwords: $PASSWORD_FILE"

echo "==> settings"
echo "    COGNITO_POOL_ID=$POOL_ID"
echo "    COGNITO_CLIENT_ID=$CLIENT_ID"
echo "    (for local runs: put both lines in the repository's .env, see TESTING_LOCALLY.md)"

if [ "${SKIP_EC2:-0}" = "1" ]; then
  echo "==> done (SKIP_EC2=1: the instance was not changed)"
  exit 0
fi

echo "==> the EC2 instance: Cognito on, development sign-in off"
DNS=$(aws ec2 describe-instances \
  --filters Name=tag:Project,Values=claimsense Name=instance-state-name,Values=running \
  --query 'Reservations[0].Instances[0].PublicDnsName' --output text)
if [ "$DNS" = "None" ] || [ -z "$DNS" ]; then
  echo "No running ClaimSense instance: start it and re-run, or use SKIP_EC2=1." >&2
  exit 1
fi
scp -i "$KEY_FILE" -q -o StrictHostKeyChecking=accept-new ../ec2/docker-compose.ec2.yml \
  "ec2-user@$DNS:/opt/claimsense/docker-compose.yml"
ssh -i "$KEY_FILE" "ec2-user@$DNS" bash -s -- "$POOL_ID" "$CLIENT_ID" "$AWS_REGION" <<'REMOTE'
set -euo pipefail
cd /opt/claimsense
grep -v -E '^(COGNITO_POOL_ID|COGNITO_CLIENT_ID|DEV_LOGIN)=' .env > .env.new || true
printf 'COGNITO_POOL_ID=%s\nCOGNITO_CLIENT_ID=%s\nDEV_LOGIN=0\n' "$1" "$2" >> .env.new
mv .env.new .env && chmod 600 .env
REGISTRY=$(sed -n 's/^REGISTRY=//p' .env)
aws ecr get-login-password --region "$3" | docker login --username AWS --password-stdin "$REGISTRY" >/dev/null
# no-deps: do not re-run the seed job, so notes and reviews stay.
docker compose pull --quiet api mcp runner web
docker compose up -d --wait --no-deps api mcp runner web
docker compose ps --format '{{.Service}}: {{.Status}}'
REMOTE
echo "==> done: sign in at http://$DNS:3100 with a user name and password from $PASSWORD_FILE"
echo "    next: AWS_PROFILE=claimsense deploy/lambda/deploy.sh (the Lambda Claims API accepts Cognito tokens)"
