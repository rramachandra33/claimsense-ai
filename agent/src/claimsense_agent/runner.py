"""The runner: a small service that runs one assessment when the console asks.

    POST /runs  {"claim_id": "CLM-2024-1800"}   with the adjuster's token as Authorization

The runner is a client of the data API like any other. It forwards the adjuster's token and has
no access rules or secrets of its own: the API decides whether this adjuster may read the claim,
issues each agent's OBO token, and accepts or refuses the note.

Start it with `make runner` (port 8100). The brain comes from CLAIMSENSE_BRAIN (default mock).
"""
import asyncio
import os

from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .api import ApiClient, api_url
from .pipeline import run_assessment
from .trace import Tracer

app = FastAPI(title="ClaimSense runner", version="0.1.0")


class RunRequest(BaseModel):
    claim_id: str


def brain():
    return os.environ.get("CLAIMSENSE_BRAIN", "mock")


def error(status, code, message):
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


@app.get("/health")
def health():
    return {"status": "ok", "brain": brain(), "api_url": api_url()}


@app.post("/runs")
def create_run(body: RunRequest, authorization: str = Header(default=None)):
    """Run the four agents on one claim as the calling adjuster, and return what happened.

    A plain `def` route runs in its own worker thread, so asyncio.run gives the run its own event
    loop and one slow run does not hold up others.
    """
    if not authorization or not authorization.startswith("Bearer "):
        return error(401, "unauthenticated", "Sign in first.")
    client = ApiClient(authorization.removeprefix("Bearer "))
    tracer = Tracer(quiet=True)
    try:
        result = asyncio.run(run_assessment(client, body.claim_id, brain=brain(), tracer=tracer))
    except NotImplementedError as e:
        return error(501, "brain_not_available", str(e))
    response = result.model_dump()
    response["brain"] = brain()
    response["duration_ms"] = round(tracer.total_ms())
    return response
