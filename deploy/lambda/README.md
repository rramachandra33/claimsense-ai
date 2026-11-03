# The Lambda Claims API

The data API (`api/`) runs on AWS Lambda as the function `claimsense-api`, behind a Function URL.
The agents on the EC2 instance (MCP server and runner) use it; the console keeps using the
instance's private API, the only one with the development sign-in.

```
console ──> api container on EC2 (dev sign-in, 127.0.0.1)          ┐
runner, MCP server ──> Function URL ──> Lambda claimsense-api ──────┼──> PostgreSQL on EC2 (5432)
                                        (default VPC, claimsense-lambda-sg)
```

## Deploy

```bash
AWS_PROFILE=claimsense deploy/ec2/deploy.sh       # first: generates the DB password, publishes 5432
AWS_PROFILE=claimsense deploy/lambda/deploy.sh    # package, create/update, URL, point the agents at it
```

`deploy.sh` packages `api/` with Linux x86_64 wheels (`uv pip install --python-platform`), creates or
updates the function (Python 3.12, 512 MB, 30 s, in the default VPC), adds the Function URL, adds
the rule "5432 from `claimsense-lambda-sg`" to the instance's security group, checks the URL,
and sets `CLAIMS_API_URL` on the instance.

## Settings on the function

| Variable | Value |
|---|---|
| `CLAIMSENSE_DB_URL` | PostgreSQL on the instance's private IP, with the generated password |
| `CLAIMSENSE_JWT_SECRET` | The same secret as the instance's API, so a token from its sign-in works here |
| `CLAIMSENSE_RATE_LIMIT_PER_MINUTE` | 300 (`RATE_LIMIT=` to change) |
| `CLAIMSENSE_DEV_LOGIN` | not set: the development sign-in answers 404 on the public URL |

The secrets are read from the instance's `/opt/claimsense/.env` and kept in the function's
environment variables (encrypted at rest by Lambda). Secrets Manager would be better, but a
function inside a VPC reaches it only through a VPC endpoint (about $7 a month); see DECISIONS.md.

## Security

- The URL is public (auth type NONE), as the app does its own token check: no token → 401, another
  adjuster's claim → 403, over the rate limit → 429, all audited.
- PostgreSQL accepts connections only from `claimsense-lambda-sg` (and on the instance itself).
- The function has no internet access (VPC, no NAT); it needs none. With Cognito, its public
  signing keys can be set as configuration.

## One-time IAM set-up (as root, in the console)

1. Role `claimsense-lambda-api`: Create role → AWS service, Lambda → AWS policy
   `AWSLambdaVPCAccessExecutionRole` (logs and the VPC network interfaces, nothing else).
2. Managed policy `ClaimSenseLambdaDeploy` from `iam/deployer-policy.json` (`ACCOUNT` = account id),
   attached to the IAM user: functions named `claimsense-*` only, pass only that role, read only
   their logs.
