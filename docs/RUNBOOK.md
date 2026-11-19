# ClaimSense AI: runbook

For an operator working alone from this repository and the AWS account. Four procedures: **add a
user**, **roll back a deployment**, **escalate a flagged claim manually**, and **update the policy
corpus**. Each ends with a check that it worked.

## Before you start

| You need | How |
|---|---|
| The repository, checked out | `git clone` (private; ask the owner for access) |
| AWS CLI v2 signed in as the deployer | `aws login --profile claimsense`, then `export AWS_PROFILE=claimsense` (never the root account) |
| The instance's SSH key | `~/.ssh/claimsense-key.pem` (from the owner; `chmod 600`) |
| Your IP allowed on ports 22 and 3100 | EC2 → Security groups → `claimsense-sg` → inbound rules |
| The instance running | `aws ec2 start-instances --instance-ids i-0e0137af99bf21cc7` |

**Find the instance's address.** It changes every time the instance starts (unless an Elastic IP is
attached):

```bash
DNS=$(aws ec2 describe-instances --filters Name=tag:Project,Values=claimsense \
        Name=instance-state-name,Values=running \
        --query 'Reservations[0].Instances[0].PublicDnsName' --output text); echo $DNS
ssh -i ~/.ssh/claimsense-key.pem ec2-user@$DNS          # a shell on the instance
```

On the instance everything runs under Docker Compose in `/opt/claimsense`. The database shell
used below is:

```bash
cd /opt/claimsense && docker compose exec -T db psql -U claimsense -d claimsense
```

**Never run `deploy/ec2/deploy.sh` or a plain `docker compose up -d` to change a running
deployment.** Starting the stack runs the `seed` job, which resets the database to the course
fixtures and **deletes every note, review and audit row**. Every procedure here restarts only the
services it needs, with `--no-deps`.

**What lives where**

| Piece | Where | Changed by |
|---|---|---|
| Console (:3100), data API, MCP server, runner, PostgreSQL 16 | EC2 `i-0e0137af99bf21cc7`, Docker Compose, images from ECR | `TAG` in `/opt/claimsense/.env` |
| The four agents | AgentCore runtime `claimsense_runner` (image `claimsense-runner:arm64-<sha>`) | `deploy/agentcore/deploy.sh` |
| Claims API and MCP server used by the agents | Lambda `claimsense-api`, `claimsense-mcp` (built from the checkout) | `deploy/lambda/deploy.sh` |
| Sign-in | Cognito pool `claimsense-users` (`us-east-1_JbOsqHvx0`) | `deploy/cognito/setup.sh` |
| Roles and suspensions | `claimsense.users` in PostgreSQL, from `data/identity/users.json` | SQL below |
| Dashboards and alarms | CloudWatch: `ClaimSense-Experience` (runs, failures, p95), `-Quality`, `-Economics`; alarms `ClaimSense-BadRuns`, `ClaimSense-SlowRuns` | `deploy/observability/setup.sh` |

---

## 1. Add a user

A person needs two records that agree: a **Cognito user** (their password) and a row in
**`claimsense.users`** (their role and status). The data API refuses a token whose group differs
from the row, and refuses a suspended user whatever Cognito says.

The roles: `adjuster` (own claims; confirms up to $25,000 net), `senior-adjuster` (all claims;
the only role that confirms above $25,000), `fraud-investigator` (own claims plus vendor fraud
score ≥ 0.70; reviews, never confirms), `total-loss-appraiser` (own claims plus repair ≥ 75% of
ACV; reviews, never confirms). See `data/identity/users.json` for the full rule.

1. **Record the user in the repository.** Add an entry to `data/identity/users.json`:

   ```json
   {"user_id": "grace", "name": "Grace Lin", "group": "adjuster", "status": "active", "test_only": false}
   ```

   The user name is lower case, letters only. Commit it: the file is the source of truth, and a
   fresh seed loads it.

2. **Add the row to the running database** (on the instance):

   ```sql
   INSERT INTO claimsense.users (user_id, full_name, user_group, status, test_only)
   VALUES ('grace', 'Grace Lin', 'adjuster', 'active', false);
   ```

3. **Create the Cognito user and its group** (from your machine). The script reads
   `users.json`, creates only the users that are missing, puts each in exactly one group, and
   writes the new password to `~/.claimsense/cognito-test-users.txt`:

   ```bash
   SKIP_EC2=1 deploy/cognito/setup.sh
   ```

   Give the password to the person over a separate channel. Do not paste it in a ticket or chat.

4. **Check.** Sign in at `http://$DNS:3100` as the new user (or have them do it). The queue
   shows only the claims their role allows; a new adjuster with no assigned claims sees an empty
   queue. On the instance:

   ```sql
   SELECT ts, user_id, action, decision, reason FROM claimsense.audit_log
    WHERE user_id = 'grace' ORDER BY ts DESC LIMIT 5;
   ```

   You should see `me` and `list_claims` rows with `allow`.

**Change a role:** update `group` in `users.json`, `UPDATE claimsense.users SET user_group = …`,
then `SKIP_EC2=1 deploy/cognito/setup.sh` (it moves the user to the one matching group). The user
signs out and in again: the old token carries the old group and is refused (401).

**Remove access:** `UPDATE claimsense.users SET status = 'suspended' WHERE user_id = 'grace';`
takes effect on the next request. Also disable the sign-in:
`aws cognito-idp admin-disable-user --user-pool-id us-east-1_JbOsqHvx0 --username grace`. Do not
delete the row: audit rows and notes refer to it.

---

## 2. Roll back a deployment

Every push to `main` that passes the tests and the evaluation gate pushes images tagged with the
commit (`claimsense-<service>:<sha>`, and `claimsense-runner:arm64-<sha>` for AgentCore) as well as
`latest`. Rolling back means pointing each piece back at the last good commit.

1. **Find the last good commit.** The previous green CI run on `main`:

   ```bash
   gh run list --branch main --workflow ci --status success --limit 5
   aws ecr describe-images --repository-name claimsense-api \
     --query 'sort_by(imageDetails,&imagePushedAt)[-5:].imageTags' --output table
   ```

   Call it `GOOD` (the full 40-character sha).

2. **Roll back the services on EC2** (console, data API, MCP server, runner). On the instance:

   ```bash
   cd /opt/claimsense
   cp .env .env.before-rollback
   sed -i "s/^TAG=.*/TAG=$GOOD/" .env
   aws ecr get-login-password --region us-east-1 | \
     docker login --username AWS --password-stdin "$(sed -n 's/^REGISTRY=//p' .env)"
   docker compose pull --quiet api mcp runner web
   docker compose up -d --wait --no-deps api mcp runner web      # --no-deps: the seed job does not run
   docker compose ps --format '{{.Service}}: {{.Status}} {{.Image}}'
   ```

3. **Roll back the agents on AgentCore** (from your machine):

   ```bash
   TAG=$GOOD deploy/agentcore/deploy.sh
   ```

   The script ends with a smoke test (one dry run, no note written). If it prints `FAILED`, it has
   already put the previous image back; pick an older `GOOD`. Every deploy runs the same test, so
   a build that breaks only on Bedrock is rolled back automatically.

4. **Roll back the Lambdas**, only if the bad change touched `api/` or `mcp_server/` (they are
   built from the checkout, not from an image):

   ```bash
   git worktree add /tmp/claimsense-good $GOOD
   (cd /tmp/claimsense-good && deploy/lambda/deploy.sh)
   git worktree remove /tmp/claimsense-good
   ```

5. **Check.**
   * `docker compose ps` shows every service healthy, with images tagged `$GOOD`.
   * Sign in and run an assessment on a claim you may change (for example CLM-2024-2165 as
     alice). A note appears within about a minute.
   * CloudWatch → `ClaimSense-Experience`: the new run appears under "Runs and failures"; the alarms `ClaimSense-BadRuns`
     and `ClaimSense-SlowRuns` return to OK within 15 minutes.
   * Note the time the check passed: the incident report needs **time to verified recovery**.

6. **Fix forward.** Revert the bad commit on `main` (`git revert <bad sha>`), push, and let CI's
   evaluation gate pass before deploying `latest` again.

If the database itself is damaged, restore is a different procedure: there is no automated
backup in the pilot (a known gap). A fresh `deploy/ec2/deploy.sh` reloads the course fixtures and
loses notes and reviews.

---

## 3. Escalate a flagged claim manually

ClaimSense never closes, pays or reassigns a claim: every note is a draft, and the claim's status
and owner belong to the claims system (`claims_mgmt.claims`, which stands in for the client's
claims-management system in the pilot). Escalation is therefore two steps: the adjuster records
their decision on the draft, and the claims system moves the claim.

When to escalate: a FLAG whose fraud indicators need an investigator (CLS-FRD-007), a ROUTE to a
specialist (total loss CLS-TL-005, injury CLS-INJ-008, above $25,000 CLS-PAY-012), or any draft the
adjuster disagrees with and cannot resolve alone.

1. **Read the draft.** In the console, open the claim and its newest note: the outcome, the
   clauses it cites, "Points for the adjuster", "Also needs", "Pending documentation", and the code
   facts. Check the cited clauses with the links (they open the policy manual).

2. **Record the decision on the draft.** Confirm it if you agree the claim needs escalation, or
   reject it with a reason. Either way, write who it goes to and why, for example
   "Escalated to SIU: VIN mismatch and two prior claims (CLS-FRD-007)". The review is stored
   beside the note with your name and time, and audited.

3. **Move the claim in the claims system.** The claims-system administrator does this, not
   ClaimSense. In the pilot, on the instance:

   ```sql
   -- to the special investigations unit (fraud indicators):
   UPDATE claims_mgmt.claims SET claim_status = 'Under Investigation', assigned_adjuster = 'carol'
    WHERE claim_id = 'CLM-2024-2165';
   -- to a total-loss appraiser:   claim_status = 'Escalated', assigned_adjuster = 'eve'
   -- to a senior adjuster:        claim_status = 'Escalated', assigned_adjuster = 'bob'
   ```

   A fraud investigator also sees, without reassignment, every claim with a vendor score of 0.70
   or more; a claim flagged for another reason (a VIN mismatch, missing police report with injury)
   must be assigned to reach them. A senior adjuster sees every claim.

4. **Check.** The new owner signs in and finds the claim in their queue. The note history shows the
   review and its reason. On the instance:

   ```sql
   SELECT ts, user_id, action, decision, reason FROM claimsense.audit_log
    WHERE action = 'review_note' ORDER BY ts DESC LIMIT 3;
   ```

The new owner may run a fresh assessment; the note then says "Second opinion: the claim was
already … in the claims system" if the claim was decided.

---

## 4. Update the policy corpus

The agents search `claimsense.clause_index` only. Every clause from the manual passes the
load-time guardrail (`platform/db/seed/guardrail.py`) first: text that reads like an instruction to
the AI goes to `claimsense.clause_quarantine` and can never be retrieved or cited.

1. **Edit the manual** in `data/course_fixtures/policy_clauses.json`. Each clause has
   `clause_id` (keep the `CLS-XXX-NNN` form; never reuse an id for different wording), `title`,
   `text` and `source`. To change wording, edit the text in place; to retire a clause, leave it
   and say so in its text, because past notes cite it.

2. **Build and check locally.**

   ```bash
   python3 platform/db/seed/build_seed.py     # prints any clause the guardrail quarantined
   make up                                    # reloads the local database
   cd platform/db/seed && python3 -m pytest -q test_seed.py && cd -
   make eval                                  # the 150 cases on the mock; must stay at 90% or more
   ```

   If a real clause is quarantined, reword it (the guardrail matches phrases such as "ignore
   previous instructions" or "approve all claims"), not the guardrail. If you add a clause, update
   the clause count in `test_seed.py`. If the change alters an outcome, the evaluation cases that
   expect the old one must be changed in `scripts/build_eval_cases.py` with the reason, and the
   change recorded in `DECISIONS.md`.

3. **Commit and push.** CI runs the tests and the gate. Then run the evaluation on Claude for the
   cases that cite the changed clause (`make eval BRAIN=bedrock` with `--cases`, or `make golden`
   for all of them).

4. **Load the new corpus on EC2 without touching notes.** Copy the three CSVs and replace the
   clause tables in one transaction:

   ```bash
   scp -i ~/.ssh/claimsense-key.pem platform/db/seed/data/{policy_clauses,clause_index,clause_quarantine}.csv \
       ec2-user@$DNS:/tmp/
   ssh -i ~/.ssh/claimsense-key.pem ec2-user@$DNS
   cd /opt/claimsense
   for f in policy_clauses clause_index clause_quarantine; do docker compose cp /tmp/$f.csv db:/tmp/$f.csv; done
   docker compose exec -T db psql -U claimsense -d claimsense -v ON_ERROR_STOP=1 <<'SQL'
   BEGIN;
   DELETE FROM claimsense.clause_index;
   DELETE FROM claimsense.clause_quarantine;
   DELETE FROM policy_admin.policy_clauses;
   COPY policy_admin.policy_clauses (clause_id, title, text, source, is_poisoned) FROM '/tmp/policy_clauses.csv' CSV HEADER;
   COPY claimsense.clause_index (clause_id, title, text) FROM '/tmp/clause_index.csv' CSV HEADER;
   COPY claimsense.clause_quarantine (clause_id, reason) FROM '/tmp/clause_quarantine.csv' CSV HEADER;
   COMMIT;
   SQL
   ```

   Nothing else needs restarting: the search index is rebuilt with the rows. Retrieval logs and
   notes keep the clause ids they recorded.

5. **Check.**

   ```sql
   SELECT (SELECT count(*) FROM claimsense.clause_index) AS indexed,
          (SELECT count(*) FROM claimsense.clause_quarantine) AS quarantined;
   ```

   In the console, open **Policy manual**, search for a word from the changed clause, and open it
   by its id. Run one assessment on a claim whose outcome rests on that clause and check the note
   cites it.

---

## Where to look when something is wrong

| Symptom | Look at |
|---|---|
| Sign-in fails for everyone | Cognito pool exists; `COGNITO_POOL_ID`/`COGNITO_CLIENT_ID` in `/opt/claimsense/.env`; `docker compose logs web api` |
| One user is refused (401/403) | `audit_log` rows for that user: the `reason` column says why (expired token, group mismatch, suspended) |
| Runs fail or take long | `ClaimSense-Experience` dashboard; alarms `ClaimSense-BadRuns` / `ClaimSense-SlowRuns`; AgentCore logs (`/aws/bedrock-agentcore/runtimes/<runtime id>-DEFAULT`); Lambda logs `/aws/lambda/claimsense-api` |
| Notes are DENY with "could not be completed" | An agent failed (`decision_source = agent_failure`): model access in Bedrock, AgentCore logs |
| Many notes use code's decision | `ClaimSense-Quality` dashboard (fallback rate); the note's `draft_problems` in the console |

Traces: the same trace id appears in the AgentCore log and the Lambda X-Ray lines for one run.
