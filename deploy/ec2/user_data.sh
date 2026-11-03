#!/bin/bash
# First-boot setup for the ClaimSense instance (Amazon Linux 2023, x86_64). Passed as user data by
# create_instance.sh; runs once, as root. Installs Docker and the Docker Compose plugin.
set -euo pipefail
dnf install -y docker
systemctl enable --now docker
usermod -aG docker ec2-user
mkdir -p /usr/local/lib/docker/cli-plugins
curl -fsSL https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-x86_64 \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
mkdir -p /opt/claimsense
chown ec2-user:ec2-user /opt/claimsense
touch /opt/claimsense/.bootstrapped
