"""The scheduled batch assessment (decided 2026-11-04). EventBridge Scheduler calls handler() every
4 hours.

1. Sign a short-lived token for the claimsense-batch service account.
2. Ask the Claims API which open claims need an assessment (never assessed, or documents changed)
   and what batch runs have cost today.
3. Run up to BATCH_MAX_CLAIMS of them on the AgentCore runtime, BATCH_PARALLEL at a time, while
   today's spend stays under BATCH_DAILY_BUDGET_USD and there is time left in this invocation.
4. Publish a summary to CloudWatch (namespace ClaimSense) and return it.

Every note it writes is a draft for the claim's assigned adjuster to confirm. A failed claim does
not stop the batch. The API applies all access rules: the batch account reads open claims only.

Locally there is no AgentCore: `claimsense-batch --runner http://localhost:8100` runs one batch
through the local runner's /invocations (the same contract), for free with the mock agents.

Settings (environment variables):
    CLAIMS_API_URL            the Claims API (the Lambda Function URL)
    AGENTCORE_RUNTIME_ARN     the runtime that runs the four agents
    CLAIMSENSE_JWT_SECRET     the token secret the API checks
    BATCH_MAX_CLAIMS          default 25
    BATCH_DAILY_BUDGET_USD    default 5
    BATCH_PARALLEL            default 3
    CLAIMSENSE_METRICS        1 to publish the summary to CloudWatch
"""
import json
import os
import time
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor

import jwt

BATCH_USER = "claimsense-batch"
BATCH_GROUP = "batch-service"
ESTIMATED_RUN_COST_USD = 0.10      # a Claude run costs about $0.06-0.08; plan with a margin
TIME_FOR_ONE_ROUND_MS = 4 * 60 * 1000   # stop starting runs when less than this is left


def setting(name, default=None):
    value = os.environ.get(name, default)
    if value is None:
        raise RuntimeError(f"{name} is not set")
    return value


def batch_token():
    """A one-hour token for the batch account, shaped like the API's development tokens."""
    now = int(time.time())
    claims = {"sub": BATCH_USER, "cognito:groups": [BATCH_GROUP], "iss": "claimsense-dev",
              "token_use": "access", "iat": now, "exp": now + 3600}
    return jwt.encode(claims, setting("CLAIMSENSE_JWT_SECRET"), algorithm="HS256")


def get_candidates(token, limit):
    """The API's answer: {"claims": [...], "needing_assessment": n, "spent_today_usd": x}."""
    url = setting("CLAIMS_API_URL").rstrip("/") + f"/api/v1/batch/candidates?limit={limit}"
    request = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def run_on_agentcore(token, claim_id):
    """Run one claim on the AgentCore runtime; return the run result (or an error result)."""
    import boto3
    from botocore.config import Config

    # One attempt only: a retry after a timeout could start a second run of the same claim.
    config = Config(read_timeout=300, retries={"total_max_attempts": 1})
    client = boto3.client("bedrock-agentcore", region_name=os.environ.get("AWS_REGION", "us-east-1"),
                          config=config)
    try:
        response = client.invoke_agent_runtime(
            agentRuntimeArn=setting("AGENTCORE_RUNTIME_ARN"),
            runtimeSessionId=f"claimsense-batch-{uuid.uuid4()}",
            contentType="application/json",
            accept="application/json",
            payload=json.dumps({"claim_id": claim_id, "user_token": token}).encode(),
        )
        return json.loads(response["response"].read())
    except Exception as e:
        return {"claim_id": claim_id, "status": "error", "problems": [f"{type(e).__name__}: {e}"]}


def run_on_runner(runner_url, token, claim_id):
    """Run one claim on a runner's /invocations (the AgentCore contract), for local testing."""
    body = json.dumps({"claim_id": claim_id, "user_token": token}).encode()
    request = urllib.request.Request(runner_url.rstrip("/") + "/invocations", data=body,
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return json.loads(response.read())
    except Exception as e:
        return {"claim_id": claim_id, "status": "error", "problems": [f"{type(e).__name__}: {e}"]}


def publish(summary):
    """The batch summary as CloudWatch metrics. A failure here never fails the batch."""
    if os.environ.get("CLAIMSENSE_METRICS") != "1":
        return
    try:
        import boto3
        boto3.client("cloudwatch").put_metric_data(Namespace="ClaimSense", MetricData=[
            {"MetricName": "BatchClaimsPicked", "Value": summary["picked"], "Unit": "Count"},
            {"MetricName": "BatchRuns", "Value": summary["runs"], "Unit": "Count"},
            {"MetricName": "BatchFailures", "Value": summary["failures"], "Unit": "Count"},
            {"MetricName": "BatchCostUsd", "Value": summary["cost_usd"], "Unit": "None"},
        ])
    except Exception as e:
        print(f"[batch] metrics not published: {type(e).__name__}: {e}")


def run_batch(run_claim, candidates_answer, max_claims, budget_usd, parallel, time_left_ms):
    """Run the picked claims in rounds of `parallel`, within the claim limit, the day's budget and
    the time left. run_claim(claim_id) returns a run result. Returns the summary."""
    queue = [c["claim_id"] for c in candidates_answer["claims"]][:max_claims]
    spent = candidates_answer["spent_today_usd"]
    results = []
    stopped = None
    while queue:
        if time_left_ms() < TIME_FOR_ONE_ROUND_MS:
            stopped = "out of time"
            break
        affordable = int((budget_usd - spent) // ESTIMATED_RUN_COST_USD)
        if affordable <= 0:
            stopped = "daily budget reached"
            break
        this_round = queue[:min(parallel, affordable)]
        queue = queue[len(this_round):]
        with ThreadPoolExecutor(max_workers=len(this_round)) as pool:
            for result in pool.map(run_claim, this_round):
                results.append(result)
                spent += result.get("cost_usd") or 0
    written = [r for r in results if r.get("status") in ("written", "replayed")]
    return {
        "needing_assessment": candidates_answer["needing_assessment"],
        "picked": len(candidates_answer["claims"][:max_claims]),
        "runs": len(written),
        "failures": len(results) - len(written),
        "not_run": len(queue),
        "stopped": stopped,
        "cost_usd": round(sum(r.get("cost_usd") or 0 for r in results), 4),
        "spent_today_usd": round(spent, 4),
        "results": [{k: r.get(k) for k in ("claim_id", "status", "outcome", "decision_source", "note_id",
                                           "cost_usd", "problems")} for r in results],
    }


def handler(event, context):
    max_claims = int(os.environ.get("BATCH_MAX_CLAIMS", "25"))
    budget = float(os.environ.get("BATCH_DAILY_BUDGET_USD", "5"))
    parallel = int(os.environ.get("BATCH_PARALLEL", "3"))
    token = batch_token()
    answer = get_candidates(token, max_claims)
    summary = run_batch(lambda claim_id: run_on_agentcore(token, claim_id), answer, max_claims, budget,
                        parallel, context.get_remaining_time_in_millis)
    print(json.dumps({"batch": summary}))
    publish(summary)
    return summary


def main():
    """One batch from the command line, through a local runner instead of AgentCore:
        CLAIMS_API_URL=http://localhost:8000 CLAIMSENSE_JWT_SECRET=... claimsense-batch --runner http://localhost:8100
    """
    import argparse

    parser = argparse.ArgumentParser(description="Run one batch assessment through a local runner.")
    parser.add_argument("--runner", default="http://localhost:8100", help="the runner's base URL")
    args = parser.parse_args()
    max_claims = int(os.environ.get("BATCH_MAX_CLAIMS", "25"))
    budget = float(os.environ.get("BATCH_DAILY_BUDGET_USD", "5"))
    parallel = int(os.environ.get("BATCH_PARALLEL", "3"))
    token = batch_token()
    answer = get_candidates(token, max_claims)
    print(f"{answer['needing_assessment']} open claims need an assessment; "
          f"${answer['spent_today_usd']:.2f} spent by batches today")
    summary = run_batch(lambda claim_id: run_on_runner(args.runner, token, claim_id), answer, max_claims,
                        budget, parallel, lambda: 15 * 60 * 1000)
    for r in summary["results"]:
        print(f"  {r['claim_id']}  {r['status']:<8} {r.get('outcome') or '':<8} note {r.get('note_id')}")
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, indent=2))


if __name__ == "__main__":
    main()
