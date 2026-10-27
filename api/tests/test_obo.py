"""Tests for on-behalf-of (OBO) agent tokens (run `make up` first).

    cd api && uv run --extra dev pytest -q
"""
import os
import uuid

os.environ.setdefault("CLAIMSENSE_JWT_SECRET", "test-secret-for-pytest-only-0123456789abcdef")

import psycopg  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from claimsense_api.auth import make_dev_token  # noqa: E402
from claimsense_api.db import db_url, execute, fetch_all  # noqa: E402
from claimsense_api.main import app  # noqa: E402
from claimsense_api.obo import make_obo_token  # noqa: E402

try:
    psycopg.connect(db_url()).close()
except psycopg.OperationalError:
    pytest.skip("database not running (run `make up`)", allow_module_level=True)

client = TestClient(app)
ALICE = {"Authorization": "Bearer " + make_dev_token("alice", "adjuster")}
CLAIM = "CLM-2024-1800"            # alice's claim
OTHER_ALICE_CLAIM = "CLM-2024-2092"


def obo_token(agent, claim_id=CLAIM, run_id=None):
    """Ask for an agent token the way pipeline code will."""
    body = {"claim_id": claim_id, "agent": agent, "run_id": run_id or str(uuid.uuid4())}
    return client.post("/api/v1/obo/token", json=body, headers=ALICE)


def as_agent(token):
    return {"Authorization": f"Bearer {token}"}


# --- issuing ------------------------------------------------------------------

def test_token_is_issued_for_a_claim_the_adjuster_can_read():
    response = obo_token("coverage")
    assert response.status_code == 200
    body = response.json()
    assert body["scopes"] == ["claim:read", "policy:read", "clauses:search"]
    assert body["expires_in"] == 300


def test_no_token_for_a_claim_the_adjuster_cannot_read():
    assert obo_token("coverage", claim_id="CLM-2024-1873").status_code == 403


def test_unknown_agent_is_refused():
    assert obo_token("payments").status_code == 400


def test_an_agent_cannot_mint_more_tokens():
    token = obo_token("coverage").json()["token"]
    body = {"claim_id": CLAIM, "agent": "reader", "run_id": str(uuid.uuid4())}
    response = client.post("/api/v1/obo/token", json=body, headers=as_agent(token))
    assert response.status_code == 403


# --- scopes ---------------------------------------------------------------------

def test_coverage_agent_can_read_claim_policy_and_search_but_not_documents():
    agent = as_agent(obo_token("coverage").json()["token"])
    assert client.get(f"/api/v1/claims/{CLAIM}", headers=agent).status_code == 200
    assert client.get(f"/api/v1/claims/{CLAIM}/policy", headers=agent).status_code == 200
    assert client.get("/api/v1/clauses?q=collision", headers=agent).status_code == 200
    assert client.get(f"/api/v1/claims/{CLAIM}/documents", headers=agent).status_code == 403
    assert client.get("/api/v1/documents/DOC-00001", headers=agent).status_code == 403


def test_reader_agent_can_read_documents_but_not_policy_or_clauses():
    agent = as_agent(obo_token("reader").json()["token"])
    assert client.get(f"/api/v1/claims/{CLAIM}/documents", headers=agent).status_code == 200
    assert client.get("/api/v1/documents/DOC-00001", headers=agent).status_code == 200
    assert client.get(f"/api/v1/claims/{CLAIM}/policy", headers=agent).status_code == 403
    assert client.get("/api/v1/clauses?q=collision", headers=agent).status_code == 403


def test_no_agent_can_list_claims_or_write_notes():
    for name in ("reader", "coverage", "risk", "drafter"):
        agent = as_agent(obo_token(name).json()["token"])
        assert client.get("/api/v1/claims", headers=agent).status_code == 403
        note = {"run_id": str(uuid.uuid4()), "outcome": "APPROVE", "summary": "x", "cited_clauses": ["CLS-COLL-001"]}
        headers = {**agent, "Idempotency-Key": "k-" + name}
        assert client.post(f"/api/v1/claims/{CLAIM}/notes", json=note, headers=headers).status_code == 403


# --- binding to one claim and one run --------------------------------------------

def test_token_is_bound_to_its_claim():
    """Even another claim the adjuster may read is refused (e.g. injected 'fetch claim X')."""
    agent = as_agent(obo_token("reader").json()["token"])
    assert client.get(f"/api/v1/claims/{OTHER_ALICE_CLAIM}", headers=agent).status_code == 403
    # DOC-00017 belongs to CLM-2024-2092, which alice may read herself: only the binding refuses it.
    assert client.get("/api/v1/documents/DOC-00017", headers=ALICE).status_code == 200
    assert client.get("/api/v1/documents/DOC-00017", headers=agent).status_code == 403


def test_searches_are_recorded_under_the_tokens_run_and_agent():
    run_id = str(uuid.uuid4())
    agent = as_agent(obo_token("coverage", run_id=run_id).json()["token"])
    fake_run = str(uuid.uuid4())
    client.get(f"/api/v1/clauses?q=collision&run_id={fake_run}&agent=drafter", headers=agent)
    rows = fetch_all("SELECT run_id::text, agent FROM claimsense.retrieval_log WHERE run_id IN (%s, %s)",
                     (run_id, fake_run))
    assert rows == [{"run_id": run_id, "agent": "coverage"}]
    execute("DELETE FROM claimsense.retrieval_log WHERE run_id = %s", (run_id,))


def test_expired_agent_token_is_refused():
    alice = {"user_id": "alice", "user_group": "adjuster"}
    expired = make_obo_token(alice, CLAIM, "coverage", str(uuid.uuid4()), expires_in=-1)
    assert client.get(f"/api/v1/claims/{CLAIM}", headers=as_agent(expired)).status_code == 401


def test_suspending_the_adjuster_stops_their_agents_mid_run():
    agent = as_agent(obo_token("coverage").json()["token"])
    assert client.get(f"/api/v1/claims/{CLAIM}", headers=agent).status_code == 200
    execute("UPDATE claimsense.users SET status = 'suspended' WHERE user_id = 'alice'")
    try:
        assert client.get(f"/api/v1/claims/{CLAIM}", headers=agent).status_code == 403
    finally:
        execute("UPDATE claimsense.users SET status = 'active' WHERE user_id = 'alice'")


# --- audit ------------------------------------------------------------------------

def test_agent_calls_are_audited_with_both_identities():
    run_id = str(uuid.uuid4())
    agent = as_agent(obo_token("coverage", run_id=run_id).json()["token"])
    client.get(f"/api/v1/claims/{CLAIM}", headers=agent)
    client.get(f"/api/v1/claims/{OTHER_ALICE_CLAIM}", headers=agent)
    rows = fetch_all("""SELECT actor, on_behalf_of, resource_id, decision FROM claimsense.audit_log
                        WHERE run_id = %s AND action = 'get_claim' ORDER BY audit_id""", (run_id,))
    assert rows[0] == {"actor": "coverage", "on_behalf_of": "alice", "resource_id": CLAIM, "decision": "allow"}
    assert rows[1]["decision"] == "deny" and rows[1]["resource_id"] == OTHER_ALICE_CLAIM
