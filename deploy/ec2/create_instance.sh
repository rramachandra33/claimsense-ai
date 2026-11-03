#!/usr/bin/env bash
# Create the ClaimSense EC2 instance: a t3.small (Amazon Linux 2023, x86_64) with its own key pair,
# security group and instance role. Safe to re-run: it reuses what already exists.
#
#   AWS_PROFILE=claimsense deploy/ec2/create_instance.sh
#
# Security group claimsense-sg lets in only your current IP, on 22 (SSH) and 3100 (the console).
# Everything is tagged Project=claimsense, the only tag the deploy rights can touch.
# Needs setup_ec2_access.sh to have run once (role claimsense-ec2, deploy rights).
set -euo pipefail
cd "$(dirname "$0")"

export AWS_REGION="${AWS_REGION:-us-east-1}"
NAME="claimsense"
KEY="claimsense-key"
KEY_FILE="$HOME/.ssh/$KEY.pem"
SG_NAME="claimsense-sg"
TAGS="{Key=Project,Value=claimsense},{Key=Name,Value=$NAME}"

MYIP=$(curl -fsS https://checkip.amazonaws.com)
echo "==> region $AWS_REGION, your IP $MYIP, as $(aws sts get-caller-identity --query Arn --output text)"

EXISTING=$(aws ec2 describe-instances \
  --filters Name=tag:Project,Values=claimsense Name=instance-state-name,Values=pending,running,stopping,stopped \
  --query 'Reservations[].Instances[].InstanceId' --output text)
if [ -n "$EXISTING" ]; then
  echo "==> instance already exists: $EXISTING (nothing to do; deploy with deploy.sh)"
  exit 0
fi

echo "==> key pair $KEY"
if aws ec2 describe-key-pairs --key-names "$KEY" >/dev/null 2>&1; then
  echo "    already there (private key expected at $KEY_FILE)"
else
  # Into a variable first, so a refused call leaves no empty key file behind.
  KEY_MATERIAL=$(aws ec2 create-key-pair --key-name "$KEY" --key-type ed25519 \
    --tag-specifications "ResourceType=key-pair,Tags=[$TAGS]" \
    --query KeyMaterial --output text)
  (umask 077; printf '%s\n' "$KEY_MATERIAL" > "$KEY_FILE")
  chmod 400 "$KEY_FILE"
  echo "    created; private key saved to $KEY_FILE"
fi

echo "==> security group $SG_NAME"
VPC=$(aws ec2 describe-vpcs --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId' --output text)
SG=$(aws ec2 describe-security-groups --filters Name=group-name,Values="$SG_NAME" Name=vpc-id,Values="$VPC" \
  --query 'SecurityGroups[0].GroupId' --output text)
if [ "$SG" = "None" ]; then
  SG=$(aws ec2 create-security-group --group-name "$SG_NAME" --vpc-id "$VPC" \
    --description "ClaimSense: SSH and console from the owner IP only" \
    --tag-specifications "ResourceType=security-group,Tags=[$TAGS]" \
    --query GroupId --output text)
  for port in 22 3100; do
    aws ec2 authorize-security-group-ingress --group-id "$SG" \
      --protocol tcp --port "$port" --cidr "$MYIP/32" >/dev/null
  done
  echo "    created $SG (22 and 3100 from $MYIP)"
else
  echo "    already there: $SG"
fi

echo "==> instance"
AMI=$(aws ssm get-parameters --names /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 \
  --query 'Parameters[0].Value' --output text)
# Hop limit 2: containers on the instance can reach the instance role's credentials (IMDSv2).
INSTANCE=$(aws ec2 run-instances --image-id "$AMI" --instance-type t3.small \
  --key-name "$KEY" --security-group-ids "$SG" \
  --iam-instance-profile Name=claimsense-ec2 \
  --metadata-options HttpTokens=required,HttpPutResponseHopLimit=2,HttpEndpoint=enabled \
  --block-device-mappings 'DeviceName=/dev/xvda,Ebs={VolumeSize=20,VolumeType=gp3,Encrypted=true}' \
  --user-data file://user_data.sh \
  --tag-specifications "ResourceType=instance,Tags=[$TAGS]" "ResourceType=volume,Tags=[$TAGS]" \
  --query 'Instances[0].InstanceId' --output text)
echo "    launched $INSTANCE ($AMI); waiting until it runs…"
aws ec2 wait instance-running --instance-ids "$INSTANCE"
DNS=$(aws ec2 describe-instances --instance-ids "$INSTANCE" \
  --query 'Reservations[0].Instances[0].PublicDnsName' --output text)
echo "==> running: $DNS"
echo "    first boot installs Docker (about 2 minutes). Then: AWS_PROFILE=claimsense deploy/ec2/deploy.sh"
