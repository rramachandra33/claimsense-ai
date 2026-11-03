"""The runner: a small service that runs one assessment when the console asks.

    POST /runs  {"claim_id": "CLM-2024-1800"}   with the adjuster's token as Authorization

It also speaks the Amazon Bedrock AgentCore Runtime contract, so the same image can run on
AgentCore:

    GET  /ping          health, answered with {"status": "Healthy"}
    POST /invocations   {"claim_id": "CLM-2024-1800", "user_token": "<the adjuster's token>"}

On AgentCore the caller signs the request with AWS credentials (SigV4), and that signature uses
the Authorization header. So /invocations takes the adjuster's token in the body instead.

The runner is a client of the data API like any other. It forwards the adjuster's token and has
no access rules or secrets of its own: the API decides whether this adjuster may read the claim,
issues each agent's OBO token, and accepts or refuses the note.

Start it with `make runner` (port 8100; AgentCore uses 8080, set by RUNNER_PORT in the image).
The brain comes from CLAIMSENSE_BRAIN (default mock).

Forwarding to AgentCore: when CLAIMSENSE_AGENTCORE_RUNTIME_ARN is set, /runs does not run the
agents here. It hands the run to that AgentCore runtime (InvokeAgentRuntime, signed with this
machine's AWS credentials) with the adjuster's token in the payload, and returns its answer. The
console then reaches AgentCore without any AWS code of its own.
"""
import asyncio
import json
import os
import uuid

from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .api import ApiClient, api_url
from .pipeline import run_assessment
from .trace import Tracer

app = FastAPI(title="ClaimSense runner", version="0.1.0")


class RunRequest(BaseModel):
    claim_id: str


class InvocationRequest(BaseModel):
    """The AgentCore payload: the claim, and the token of the adjuster the run acts for."""
    claim_id: str
    user_token: str | None = None


def brain():
    return os.environ.get("CLAIMSENSE_BRAIN", "mock")


def error(status, code, message):
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def agentcore_runtime_arn():
    return os.environ.get("CLAIMSENSE_AGENTCORE_RUNTIME_ARN", "")


def forward_to_agentcore(token, claim_id):
    """Run the assessment on the AgentCore runtime instead of here, and return its answer."""
    import boto3   # only needed in this mode
    from botocore.config import Config

    # A Claude run takes about 30-60 s. One attempt only: a retry after a timeout could start a
    # second run of the same claim.
    config = Config(read_timeout=300, retries={"total_max_attempts": 1})
    client = boto3.client("bedrock-agentcore", region_name=os.environ.get("AWS_REGION", "us-east-1"),
                          config=config)
    try:
        response = client.invoke_agent_runtime(
            agentRuntimeArn=agentcore_runtime_arn(),
            runtimeSessionId=f"claimsense-run-{uuid.uuid4()}",     # at least 33 characters
            contentType="application/json",
            accept="application/json",
            payload=json.dumps({"claim_id": claim_id, "user_token": token}).encode(),
        )
        return json.loads(response["response"].read())
    except Exception as e:
        print(f"[runner] AgentCore call failed: {type(e).__name__}: {e}")
        return error(502, "agentcore_failed", "The assessment service did not answer. Try again.")


@app.get("/health")
def health():
    return {"status": "ok", "brain": brain(), "api_url": api_url(),
            "agentcore_runtime": agentcore_runtime_arn() or None}


@app.get("/ping")
def ping():
    """AgentCore's health check."""
    return {"status": "Healthy"}


def assess(token, claim_id):
    """Run the four agents on one claim as the adjuster whose token this is; return what happened."""
    client = ApiClient(token)
    tracer = Tracer(quiet=True)
    try:
        result = asyncio.run(run_assessment(client, claim_id, brain=brain(), tracer=tracer))
    except NotImplementedError as e:
        return error(501, "brain_not_available", str(e))
    response = result.model_dump()
    response["brain"] = brain()
    response["duration_ms"] = round(tracer.total_ms())
    return response


@app.post("/runs")
def create_run(body: RunRequest, authorization: str = Header(default=None)):
    """Run the four agents on one claim as the calling adjuster (the console's Run assessment).

    A plain `def` route runs in its own worker thread, so asyncio.run gives the run its own event
    loop and one slow run does not hold up others.
    """
    if not authorization or not authorization.startswith("Bearer "):
        return error(401, "unauthenticated", "Sign in first.")
    token = authorization.removeprefix("Bearer ")
    if agentcore_runtime_arn():
        return forward_to_agentcore(token, body.claim_id)
    return assess(token, body.claim_id)


@app.post("/invocations")
def invoke(body: InvocationRequest):
    """The same run, called through AgentCore. The adjuster's token comes in the body."""
    if not body.user_token:
        return error(401, "unauthenticated", "Send the adjuster's token as user_token.")
    return assess(body.user_token, body.claim_id)
