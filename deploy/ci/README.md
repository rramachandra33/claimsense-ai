# CI: tests, the evaluation gate, and the image push

`.github/workflows/ci.yml` runs on every push and pull request:

1. **test-and-eval**: the database and course data (the same `db` and `seed` containers as
   `make stack`), then the seed, data API, MCP server and agent tests, then the evaluation gate:
   the 150 cases on the mock brain, which fails below a 90% pass rate. The results file is kept as
   the `eval-results` artifact.
2. **push-images** (pushes to `main` only, and only if step 1 passed): builds the api, runner, web
   and seed images and pushes them to Amazon ECR, tagged with the commit SHA and `latest`.

## AWS access: GitHub OIDC, no stored keys

GitHub gives the job a short-lived identity token; AWS exchanges it for temporary credentials of
the role `claimsense-github-ci`. The role's trust policy accepts only pushes to `main` of
`rramachandra33/claimsense-ai`, identified by GitHub's immutable owner and repository ids
(`repo:rramachandra33@20261454/claimsense-ai@1435070108`, read from GitHub by the script), and its
only permission is pushing to the four
`claimsense-*` ECR repositories.

One-time set-up, with an identity that can manage IAM and ECR (not the Bedrock-only `claimsense`
profile):

```bash
AWS_PROFILE=<admin profile> deploy/ci/setup_github_oidc.sh
```

It is safe to re-run. It creates the GitHub OIDC provider (if the account does not have it), the
ECR repositories `claimsense-api`, `-runner`, `-web` and `-seed` (scan on push, last 10 images
kept), and the role with its `ecr-push` policy.
