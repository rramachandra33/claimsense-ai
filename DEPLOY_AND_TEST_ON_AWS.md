# Deploy and test ClaimSense on AWS, from scratch

The order to build the whole AWS deployment in a new account, then how to test every feature on
it. Local testing has its own guide: `TESTING_LOCALLY.md`. Region: **us-east-1**. Each step's
details are in the README of its folder under `deploy/`.

```
GitHub Actions (OIDC) ──> ECR images
Amazon Cognito (pool claimsense-users) <── console sign-in (user name + password)
EC2 t3.small: PostgreSQL · console :3100 · API · MCP · runner ──forwards──┐
Lambda claimsense-api (Claims API, in the VPC) <── agents          AgentCore claimsense_runner (Claude)
Lambda claimsense-mcp (MCP server + registry)  <── agents  <───────┘
EventBridge Scheduler (every 4 h) ──> Lambda claimsense-batch ──> AgentCore
CloudWatch: spans, metrics, 3 dashboards, 2 alarms
```

## 0. Before you start

- An AWS account with root access for the one-time IAM steps (there is no admin CLI profile).
- An IAM user (here `rramachandra33`) with the CLI profile `claimsense`, signed in with
  `aws login --profile claimsense` (a private browser window if the browser is signed in as root).
  **Never use root for the app.**
- Bedrock model access in us-east-1 for Claude Haiku 4.5 and Claude Sonnet 4.5.
- The GitHub repository (private) and the `gh` CLI signed in. The tools from `TESTING_LOCALLY.md` §1.
- In every IAM policy file below, replace `ACCOUNT` with the account id.

## 1. One-time IAM set-up (as root, in the console)

| # | What | File(s) | Notes |
|---|---|---|---|
| 1 | User inline policy for Claude on Bedrock | the `ClaudeOnBedrock` statement of `deploy/ec2/iam/instance-role-policy.json` | for local Claude runs and `make golden` |
| 2 | CI: OIDC provider, 4 ECR repos, role `claimsense-github-ci` | `deploy/ci/setup_github_oidc.sh` | needs IAM and ECR rights: run it with a temporary narrow inline policy on the user, then remove that policy; see `deploy/ci/README.md` |
| 3 | EC2: role `claimsense-ec2` (inline `ClaimSenseInstance`), managed policy `ClaimSenseEc2Deploy` on the user | `deploy/ec2/iam/*.json` | `deploy/ec2/EC2_DEPLOY.md` |
| 4 | Lambda: role `claimsense-lambda-api` (managed `AWSLambdaVPCAccessExecutionRole`), managed policy `ClaimSenseLambdaDeploy` on the user | `deploy/lambda/iam/deployer-policy.json` | `deploy/lambda/README.md` |
| 5 | AgentCore: role `claimsense-agentcore` (custom trust + inline), managed policy `ClaimSenseAgentCoreDeploy` on the user | `deploy/agentcore/iam/*.json` | `deploy/agentcore/README.md` |
| 6 | Observability: managed policy `ClaimSenseObservability` on the user; CloudWatch → Settings → **Transaction Search → Enable** | `deploy/observability/iam/deployer-policy.json` | the CI role's `eval-metrics` comes from step 2 |
| 7 | Batch: roles `claimsense-batch-lambda` and `claimsense-batch-scheduler` (custom trust + inline), managed policy `ClaimSenseBatchDeploy` on the user | `deploy/batch/iam/*.json` | `deploy/batch/README.md` |
| 8 | Cognito: managed policy `ClaimSenseCognitoDeploy` on the user (create and set up user pools; no delete) | `deploy/cognito/iam/deployer-policy.json` | `deploy/cognito/README.md` |

Checks that save time (each one cost a retry before):

- A managed policy does nothing until it is **attached to the user** (Users → the user →
  Permissions). A user can have at most 10 attached managed policies; past that, add the
  statements to an existing ClaimSense policy instead.
- After editing a policy, its new version must be the **default** version.
- Use managed policies, not inline: all inline policies of one user share 2,048 characters.
- A role must exist under exactly the name the scripts use; "The role defined for the function
  cannot be assumed by Lambda" means the role is missing or its trust policy is wrong.
- The first AgentCore runtime creates service-linked roles: step 5's policy allows that.

## 2. Images (CI)

Push to `main`. GitHub Actions runs every test and the evaluation gate (60 cases, mock, at least
90%), then pushes `claimsense-api`, `-runner` (amd64 and arm64), `-web` and `-seed` to ECR, tagged
with the commit and `latest`. Check: `gh run list --limit 1` shows success, and ECR (us-east-1) has
the four repositories.

## 3. Deploy, in this order (all with `AWS_PROFILE=claimsense`)

```bash
export AWS_PROFILE=claimsense
deploy/ec2/create_instance.sh        # once: key pair ~/.ssh/claimsense-key.pem, security group, t3.small
deploy/ec2/deploy.sh                 # the stack on EC2; generates the DB password and token secret; RESETS the data
deploy/cognito/setup.sh              # Cognito pool, app client, groups, test users (passwords in ~/.claimsense/);
                                     # EC2: Cognito sign-in on, development sign-in off
deploy/lambda/deploy.sh              # claimsense-api and claimsense-mcp, their URLs; points the agents at them;
                                     # gives claimsense-api the pool's public keys
deploy/agentcore/deploy.sh           # the runtime claimsense_runner (Claude); the console's runs go to it
deploy/observability/setup.sh        # dashboards and alarms
SCHEDULE_STATE=DISABLED deploy/batch/deploy.sh   # the batch Lambda and its schedule, paused; applies the DB change
```

The console is at `http://<public DNS>:3100`. **`<public DNS>` everywhere in this guide** is the
instance's public address, for example `ec2-18-208-221-165.compute-1.amazonaws.com`. It changes
every time the instance is stopped and started, so look it up after each start (`deploy/ec2/deploy.sh`
also prints it at the end):

```bash
aws ec2 describe-instances --filters Name=tag:Project,Values=claimsense Name=instance-state-name,Values=running \
  --query 'Reservations[0].Instances[0].PublicDnsName' --output text
```

The security group allows 3100 and 22 only from the IP that created it. If the page times out,
compare `curl -s https://checkip.amazonaws.com` with the inbound rules of `claimsense-sg` and add
your new IP. Or use an SSH tunnel and open `http://localhost:3100` (stop a local `make stack` first,
it uses the same port):

```bash
ssh -i ~/.ssh/claimsense-key.pem -N -L 3100:localhost:3100 ec2-user@<public DNS>
```

**Updating later** (after a push and a green CI): re-run only what changed. `deploy/ec2/deploy.sh`
reloads the course data (it removes notes); to keep them, update the containers instead:

```bash
ssh -i ~/.ssh/claimsense-key.pem ec2-user@<public DNS> 'cd /opt/claimsense &&
  aws ecr get-login-password --region us-east-1 | docker login -u AWS --password-stdin $(grep ^REGISTRY .env | cut -d= -f2) &&
  docker compose pull api mcp runner web && docker compose up -d --no-deps api mcp runner web'
```

Database changes for an existing database are in `platform/db/migrations/` (each is safe to run
twice): `ssh … 'cd /opt/claimsense && docker compose exec -T db psql -U claimsense -d claimsense' < <file>`.

## 4. Test every feature on AWS

### 4.1 The console (runs go to Claude on AgentCore: about 30–60 s and $0.06–0.08 each)

Repeat `TESTING_LOCALLY.md` §3.1–3.3 on `http://<public DNS>:3100`, signing in with a user name
and the password from `~/.claimsense/cognito-test-users.txt`. On AWS the outcomes come from
Claude, so wording differs; the decision rules do not. Expected:

| Check | Expect |
|---|---|
| alice on CLM-2024-3041 | the rerun question, then APPROVE; the spinner counts seconds; cost about $0.07 in "How this was reached" |
| alice on CLM-2024-1800 | FLAG for the location difference, "Second opinion: the claim was already Approved…" |
| bob on CLM-2024-1873 | FLAG, with "Also needs: ROUTE … senior adjuster (CLS-PAY-012)" and "Pending documentation" |
| alice on CLM-2024-1873 | "Not available" (carol's claim) |
| Confirm / Reject | as locally; carol and eve have no buttons |

### 4.2 Cognito sign-in

| Check | Expect |
|---|---|
| `alice` with her password | the claims list (6 claims); Run assessment works: her Cognito token goes through the runner and AgentCore to the Lambda API, which mints the agents' tokens |
| `alice` with a wrong password | "Wrong user name or password." |
| `frank` with his password | "Your account may not use ClaimSense." (suspended in ClaimSense) |
| `claimsense-batch` | "Wrong user name or password." (not in the pool) |
| the development sign-in on EC2 | `ssh … 'curl -s -o /dev/null -w "%{http_code}\n" -X POST localhost:8000/api/v1/dev/login -H "content-type: application/json" -d "{\"user_id\":\"alice\"}"'` → **404** |

A Cognito token against the Lambda API by hand (type the password when asked; it is not stored):

```bash
POOL=$(aws cognito-idp list-user-pools --max-results 60 --query "UserPools[?Name=='claimsense-users'].Id | [0]" --output text)
CLIENT=$(aws cognito-idp list-user-pool-clients --user-pool-id $POOL --query "UserPoolClients[0].ClientId" --output text)
printf "alice's password: "; read -s PW; echo
TOKEN=$(aws cognito-idp initiate-auth --client-id $CLIENT --auth-flow USER_PASSWORD_AUTH \
  --auth-parameters USERNAME=alice,PASSWORD="$PW" --query AuthenticationResult.AccessToken --output text); unset PW
API=$(aws lambda get-function-url-config --function-name claimsense-api --query FunctionUrl --output text)
curl -s ${API}api/v1/me -H "Authorization: Bearer $TOKEN"        # {"user_id":"alice",...}
```

### 4.3 The Lambda functions

```bash
API=$(aws lambda get-function-url-config --function-name claimsense-api --query FunctionUrl --output text)
MCP=$(aws lambda get-function-url-config --function-name claimsense-mcp --query FunctionUrl --output text)
curl -s ${API}api/v1/health                                     # {"status":"ok",...}
curl -s -o /dev/null -w '%{http_code}\n' ${API}api/v1/claims     # 401: no token
curl -s -o /dev/null -w '%{http_code}\n' -X POST ${API}api/v1/dev/login -H 'content-type: application/json' -d '{"user_id":"alice"}'
                                                                # 404: no development sign-in on the public URL
curl -s ${MCP}registry/v0/servers                               # the MCP registry: io.claimsense/claims
```

### 4.4 AgentCore

`aws bedrock-agentcore-control list-agent-runtimes` shows `claimsense_runner` READY. Each console
run appears in the log group `/aws/bedrock-agentcore/runtimes/<runtime id>-DEFAULT`.

### 4.5 Observability (CloudWatch, us-east-1)

- Dashboards **ClaimSense-Experience**, **-Economics**, **-Quality**: after a few runs, run duration
  (p50/p95), cost per resolution, decisions by outcome; the evaluation pass rate from CI.
- Alarms **ClaimSense-SlowRuns**, **ClaimSense-BadRuns** (OK, or INSUFFICIENT_DATA when idle).
- Traces: Logs Insights on `aws/spans`: `stats count(*) as n by name | sort n desc` shows `code facts`,
  `reader`, `coverage`, `risk`, `drafter`, `check draft`, `write note`.

### 4.6 The batch assessment

```bash
aws scheduler get-schedule --name claimsense-batch-every-4h --query State     # "DISABLED" while paused
aws lambda invoke --function-name claimsense-batch --invocation-type Event /dev/null   # one batch now
aws logs tail /aws/lambda/claimsense-batch --follow                            # the summary line {"batch": …}
```

On fresh data a batch picks the 14 open claims (about $1, 5 minutes in rounds of 3); a second batch
picks none. In the console the notes say "by the scheduled batch". CloudWatch shows `BatchRuns`,
`BatchFailures`, `BatchCostUsd`. Switch the schedule on with `deploy/batch/deploy.sh` (default
`ENABLED`); off again with `SCHEDULE_STATE=DISABLED`.

## 5. Day to day: cost, stop and start

| Resource | Cost |
|---|---|
| EC2 t3.small | about $0.02 an hour while running, plus about $1.60 a month for the disk |
| Lambdas, AgentCore, Scheduler | nothing while idle |
| Claude | about $0.07 per assessment; a batch of 14 about $1; `make golden` about $3.50 |
| CloudWatch | a few cents a month at this volume |
| Cognito | nothing (first 10,000 monthly active users free) |

```bash
aws ec2 stop-instances  --instance-ids <id>      # between sessions
aws ec2 start-instances --instance-ids <id>      # the public DNS changes; the private IP does not,
                                                 # so the Lambdas and AgentCore keep working
```

The containers and the notes come back on start; no redeploy is needed. While the instance is
stopped, the batch and every assessment fail (the database is on it): pause the schedule first.

## 6. Tear down (when the project is over)

Schedule and `claimsense-batch` Lambda → `claimsense-api` and `claimsense-mcp` Lambdas → the
AgentCore runtime → dashboards and alarms → the Cognito pool (turn deletion protection off first) → terminate the instance, delete `claimsense-sg`,
`claimsense-lambda-sg` and the key pair → the ECR repositories → the IAM roles and policies.
