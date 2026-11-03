#!/usr/bin/env bash
# One-time IAM set-up for the ClaimSense EC2 instance. Safe to re-run.
#
#   1. Role claimsense-ec2 (+ instance profile of the same name) for the instance: pull the
#      claimsense-* images from ECR and call the two Claude models on Bedrock. Nothing else.
#   2. Managed policy ClaimSenseEc2Deploy, attached to the IAM user, so the claimsense profile can launch
#      the instance (a t3.small tagged Project=claimsense only) and start, stop or change only
#      resources tagged Project=claimsense. Other instances (e.g. ClarityFi's) stay out of reach.
#      (Managed, not inline: a user's inline policies share a 2,048-character limit.)
#
# The same can be done in the console as root: see EC2_DEPLOY.md.
#
# Needs an identity allowed to manage IAM (the claimsense profile is not):
#   AWS_PROFILE=<admin profile> deploy/ec2/setup_ec2_access.sh
set -euo pipefail
cd "$(dirname "$0")"

ROLE="claimsense-ec2"
DEPLOY_USER="${DEPLOY_USER:-rramachandra33}"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
echo "==> account $ACCOUNT, as $(aws sts get-caller-identity --query Arn --output text)"

# The policy files say ACCOUNT where the account id goes.
with_account() { sed "s/ACCOUNT/$ACCOUNT/g" "$1"; }

echo "==> 1. instance role $ROLE"
if aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
  echo "    role already there"
else
  aws iam create-role --role-name "$ROLE" \
    --assume-role-policy-document file://iam/instance-role-trust.json \
    --tags Key=Project,Value=claimsense >/dev/null
  echo "    role created"
fi
aws iam put-role-policy --role-name "$ROLE" --policy-name ClaimSenseInstance \
  --policy-document "$(with_account iam/instance-role-policy.json)"
if aws iam get-instance-profile --instance-profile-name "$ROLE" >/dev/null 2>&1; then
  echo "    instance profile already there"
else
  aws iam create-instance-profile --instance-profile-name "$ROLE" >/dev/null
  aws iam add-role-to-instance-profile --instance-profile-name "$ROLE" --role-name "$ROLE"
  echo "    instance profile created"
fi

echo "==> 2. deploy rights for user $DEPLOY_USER"
POLICY_ARN="arn:aws:iam::$ACCOUNT:policy/ClaimSenseEc2Deploy"
if aws iam get-policy --policy-arn "$POLICY_ARN" >/dev/null 2>&1; then
  # Replace the policy's text: drop the oldest saved version if all five slots are used.
  OLD=$(aws iam list-policy-versions --policy-arn "$POLICY_ARN" \
    --query 'Versions[?!IsDefaultVersion].VersionId' --output text | awk '{print $NF}')
  if [ "$(aws iam list-policy-versions --policy-arn "$POLICY_ARN" --query 'length(Versions)')" -ge 5 ]; then
    aws iam delete-policy-version --policy-arn "$POLICY_ARN" --version-id "$OLD"
  fi
  aws iam create-policy-version --policy-arn "$POLICY_ARN" --set-as-default \
    --policy-document "$(with_account iam/deployer-policy.json)" >/dev/null
  echo "    policy updated"
else
  aws iam create-policy --policy-name ClaimSenseEc2Deploy \
    --policy-document "$(with_account iam/deployer-policy.json)" >/dev/null
  echo "    policy created"
fi
aws iam attach-user-policy --user-name "$DEPLOY_USER" --policy-arn "$POLICY_ARN"
echo "    ClaimSenseEc2Deploy attached to $DEPLOY_USER"
echo "==> done"
