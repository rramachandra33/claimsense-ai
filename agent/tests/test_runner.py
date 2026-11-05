"""The runner service, as the console calls it and as AgentCore calls it (run `make up` first)."""
from fastapi.testclient import TestClient

from claimsense_agent.runner import app
from conftest import RUN_IDS

runner = TestClient(app)


def bearer(user_id, group):
    from claimsense_api.auth import make_dev_token
    return {"Authorization": "Bearer " + make_dev_token(user_id, group)}


def test_run_writes_a_note_for_the_signed_in_adjuster(live_api):
    response = runner.post("/runs", json={"claim_id": "CLM-2024-3041"}, headers=bearer("alice", "adjuster"))
    assert response.status_code == 200
    body = response.json()
    RUN_IDS.append(body["run_id"])
    assert body["status"] == "written"
    assert body["outcome"] == "APPROVE"
    assert body["brain"] == "mock"


def test_run_on_a_claim_the_adjuster_cannot_read_fails_without_detail(live_api):
    response = runner.post("/runs", json={"claim_id": "CLM-2024-1873"}, headers=bearer("alice", "adjuster"))
    body = response.json()
    RUN_IDS.append(body["run_id"])
    assert body["status"] == "failed"
    assert body["problems"] == ["claim not available (403 forbidden)"]


def test_run_needs_a_token(live_api):
    response = runner.post("/runs", json={"claim_id": "CLM-2024-3041"})
    assert response.status_code == 401


def test_ping_answers_the_agentcore_health_check():
    assert runner.get("/ping").json() == {"status": "Healthy"}


def test_invocation_runs_as_the_adjuster_in_the_payload(live_api):
    token = bearer("alice", "adjuster")["Authorization"].removeprefix("Bearer ")
    response = runner.post("/invocations", json={"claim_id": "CLM-2024-3041", "user_token": token})
    assert response.status_code == 200
    body = response.json()
    RUN_IDS.append(body["run_id"])
    assert body["status"] == "written"
    assert body["outcome"] == "APPROVE"


def test_invocation_keeps_the_access_rules(live_api):
    token = bearer("alice", "adjuster")["Authorization"].removeprefix("Bearer ")
    body = runner.post("/invocations", json={"claim_id": "CLM-2024-1873", "user_token": token}).json()
    RUN_IDS.append(body["run_id"])
    assert body["status"] == "failed"
    assert body["problems"] == ["claim not available (403 forbidden)"]


def test_invocation_needs_the_adjusters_token(live_api):
    response = runner.post("/invocations", json={"claim_id": "CLM-2024-3041"})
    assert response.status_code == 401


def test_runs_are_forwarded_to_agentcore_when_a_runtime_is_set(monkeypatch):
    """With a runtime ARN, /runs sends the claim and the adjuster's token to AgentCore."""
    import io
    import json
    from claimsense_agent import runner as runner_module

    sent = {}

    class FakeAgentCore:
        def invoke_agent_runtime(self, **request):
            sent.update(request)
            answer = {"status": "written", "outcome": "APPROVE", "brain": "bedrock"}
            return {"response": io.BytesIO(json.dumps(answer).encode())}

    monkeypatch.setenv("CLAIMSENSE_AGENTCORE_RUNTIME_ARN", "arn:aws:bedrock-agentcore:us-east-1:1:runtime/x")
    monkeypatch.setattr("boto3.client", lambda *args, **kwargs: FakeAgentCore())
    headers = bearer("alice", "adjuster")
    response = runner.post("/runs", json={"claim_id": "CLM-2024-3041"}, headers=headers)
    assert response.json()["outcome"] == "APPROVE"
    assert sent["agentRuntimeArn"].endswith("runtime/x")
    assert len(sent["runtimeSessionId"]) >= 33
    payload = json.loads(sent["payload"])
    assert payload == {"claim_id": "CLM-2024-3041",
                       "user_token": headers["Authorization"].removeprefix("Bearer ")}
    assert runner_module.agentcore_runtime_arn()
