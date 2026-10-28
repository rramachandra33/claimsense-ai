#!/usr/bin/env bash
# One-time AWS set-up for the CI image push (.github/workflows/ci.yml). Safe to re-run.
#
#   1. GitHub's OIDC identity provider (one per AWS account)
#   2. ECR repositories: claimsense-api, -runner, -web, -seed (scan on push, keep the last 10 images)
#   3. IAM role claimsense-github-ci: only pushes to main of the GitHub repo can assume it, and it
#      can only push images to those four repositories
#
# Needs an identity allowed to manage IAM and ECR (the claimsense profile is Bedrock-only).
#   AWS_PROFILE=<admin profile> deploy/ci/setup_github_oidc.sh
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
GITHUB_REPO="rramachandra33/claimsense-ai"
ROLE="claimsense-github-ci"
IMAGES=(api runner web seed)

# The start of the OIDC token's "sub" claim. This repository uses GitHub's immutable form
# (owner@id/name@id), so a deleted-and-recreated repo of the same name cannot assume the role.
# Read it from GitHub when gh is available; otherwise set GITHUB_SUB_PREFIX.
SUB_PREFIX="${GITHUB_SUB_PREFIX:-$(gh api "repos/$GITHUB_REPO/actions/oidc/customization/sub" --jq .sub_claim_prefix)}"

ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
echo "==> account $ACCOUNT, region $REGION, as $(aws sts get-caller-identity --query Arn --output text)"
echo "    trusting $SUB_PREFIX:ref:refs/heads/main"

echo "==> 1. GitHub OIDC provider"
PROVIDER_ARN="arn:aws:iam::$ACCOUNT:oidc-provider/token.actions.githubusercontent.com"
if aws iam get-open-id-connect-provider --open-id-connect-provider-arn "$PROVIDER_ARN" >/dev/null 2>&1; then
  echo "    already there"
else
  aws iam create-open-id-connect-provider --url https://token.actions.githubusercontent.com \
    --client-id-list sts.amazonaws.com >/dev/null
  echo "    created"
fi

echo "==> 2. ECR repositories"
REPO_ARNS=()
for name in "${IMAGES[@]}"; do
  repo="claimsense-$name"
  if ! aws ecr describe-repositories --region "$REGION" --repository-names "$repo" >/dev/null 2>&1; then
    aws ecr create-repository --region "$REGION" --repository-name "$repo" \
      --image-scanning-configuration scanOnPush=true >/dev/null
    echo "    created $repo"
  else
    echo "    $repo already there"
  fi
  aws ecr put-lifecycle-policy --region "$REGION" --repository-name "$repo" --lifecycle-policy-text \
    '{"rules":[{"rulePriority":1,"description":"keep the last 10 images","selection":{"tagStatus":"any","countType":"imageCountMoreThan","countNumber":10},"action":{"type":"expire"}}]}' >/dev/null
  REPO_ARNS+=("\"arn:aws:ecr:$REGION:$ACCOUNT:repository/$repo\"")
done

echo "==> 3. IAM role $ROLE"
TRUST=$(cat <<JSON
{"Version": "2012-10-17",
 "Statement": [{
   "Effect": "Allow",
   "Principal": {"Federated": "$PROVIDER_ARN"},
   "Action": "sts:AssumeRoleWithWebIdentity",
   "Condition": {"StringEquals": {
     "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
     "token.actions.githubusercontent.com:sub": "$SUB_PREFIX:ref:refs/heads/main"}}}]}
JSON
)
PUSH=$(cat <<JSON
{"Version": "2012-10-17",
 "Statement": [
   {"Effect": "Allow", "Action": "ecr:GetAuthorizationToken", "Resource": "*"},
   {"Effect": "Allow",
    "Action": ["ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart",
               "ecr:CompleteLayerUpload", "ecr:PutImage", "ecr:BatchGetImage",
               "ecr:GetDownloadUrlForLayer"],
    "Resource": [$(IFS=,; echo "${REPO_ARNS[*]}")]}]}
JSON
)
if aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
  aws iam update-assume-role-policy --role-name "$ROLE" --policy-document "$TRUST"
  echo "    trust policy updated"
else
  aws iam create-role --role-name "$ROLE" --assume-role-policy-document "$TRUST" \
    --description "GitHub Actions (main of $GITHUB_REPO) pushes ClaimSense images to ECR" >/dev/null
  echo "    created"
fi
aws iam put-role-policy --role-name "$ROLE" --policy-name ecr-push --policy-document "$PUSH"
echo "    ecr-push policy set"

echo "==> done. Role: arn:aws:iam::$ACCOUNT:role/$ROLE (the AWS_ROLE_ARN in .github/workflows/ci.yml)"
