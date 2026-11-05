"""Tests for the batch assessment's API side (run `make up` first).

The claimsense-batch service account reads open claims only, asks which claims need an assessment
(never assessed, or documents changed), and its notes are written for the assigned adjuster.
"""
import os
import uuid

os.environ.setdefault("CLAIMSENSE_JWT_SECRET", "test-secret-for-pytest-only-0123456789abcdef")

import psycopg  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from claimsense_api.auth import make_dev_token  # noqa: E402
from claimsense_api.db import db_url, execute, fetch_one  # noqa: E402
from claimsense_api.main import app  # noqa: E402

try:
    psycopg.connect(db_url()).close()
except psycopg.OperationalError:
    pytest.skip("database not running (run `make up`)", allow_module_level=True)

client = TestClient(app)
BATCH = {"Authorization": "Bearer " + make_dev_token("claimsense-batch", "batch-service")}
ALICE = {"Authorization": "Bearer " + make_dev_token("alice", "adjuster")}
OPEN_CLAIM = "CLM-2024-2165"        # alice's, Pending Review, no police report
DECIDED_CLAIM = "CLM-2024-1800"     # alice's, Approved


@pytest.fixture
def run_id():
    rid = str(uuid.uuid4())
    yield rid
    for sql in (
        """DELETE FROM claims_mgmt.note_reviews WHERE note_id IN (SELECT n.note_id FROM claims_mgmt.claim_notes n
             JOIN claimsense.assessments a USING (assessment_id) WHERE a.run_id = %s)""",
        """DELETE FROM claimsense.idempotency_keys WHERE note_id IN (SELECT n.note_id FROM claims_mgmt.claim_notes n
             JOIN claimsense.assessments a USING (assessment_id) WHERE a.run_id = %s)""",
        """DELETE FROM claims_mgmt.claim_notes WHERE assessment_id IN
             (SELECT assessment_id FROM claimsense.assessments WHERE run_id = %s)""",
        "DELETE FROM claimsense.assessments WHERE run_id = %s",
        "DELETE FROM claimsense.retrieval_log WHERE run_id = %s",
    ):
        execute(sql, (rid,))


def batch_note(run_id, claim_id=OPEN_CLAIM, cost=0.07):
    """Write a note as the batch account would, citing a clause it retrieved in the run."""
    client.get("/api/v1/clauses", params={"q": "fraud investigation SIU referral", "run_id": run_id,
                                          "agent": "risk"}, headers=BATCH)
    body = {"run_id": run_id, "outcome": "FLAG", "summary": "Draft FLAG, pending adjuster confirmation.",
            "cited_clauses": ["CLS-FRD-007"], "agent_outputs": {"usage": {"cost_usd": cost}}}
    return client.post(f"/api/v1/claims/{claim_id}/notes", json=body,
                       headers={**BATCH, "Idempotency-Key": "batch-" + run_id})


def picked():
    body = client.get("/api/v1/batch/candidates", headers=BATCH).json()
    return {c["claim_id"]: c["reason"] for c in body["claims"]}, body


def test_batch_reads_open_claims_only():
    assert client.get(f"/api/v1/claims/{OPEN_CLAIM}", headers=BATCH).status_code == 200
    assert client.get(f"/api/v1/claims/{DECIDED_CLAIM}", headers=BATCH).status_code == 403


def test_only_the_batch_account_may_ask_for_candidates():
    assert client.get("/api/v1/batch/candidates", headers=ALICE).status_code == 403
    claims, body = picked()
    assert body["count"] == len(claims) <= 25
    statuses = {c["claim_status"] for c in body["claims"]}
    assert statuses <= {"Pending Review", "Under Investigation", "Escalated"}
    assert DECIDED_CLAIM not in claims


def test_a_batch_note_is_for_the_assigned_adjuster_and_drops_the_claim_until_documents_change(run_id):
    before, _ = picked()
    assert before[OPEN_CLAIM] == "never assessed"
    spent_before = picked()[1]["spent_today_usd"]

    response = batch_note(run_id)
    assert response.status_code == 201, response.json()
    note = response.json()["note"]
    assert note["on_behalf_of"] == "alice" and note["author"] == "claimsense-batch"
    row = fetch_one("SELECT trigger, documents_fingerprint FROM claimsense.assessments WHERE run_id = %s", (run_id,))
    assert row["trigger"] == "batch" and row["documents_fingerprint"]

    after, body = picked()
    assert OPEN_CLAIM not in after                                  # assessed, documents unchanged
    assert body["spent_today_usd"] == pytest.approx(spent_before + 0.07)

    doc = fetch_one("""SELECT document_id, ocr_text FROM doc_store.documents
                        WHERE claim_id = %s AND ocr_text IS NOT NULL ORDER BY document_id LIMIT 1""", (OPEN_CLAIM,))
    execute("UPDATE doc_store.documents SET ocr_text = ocr_text || ' (amended)' WHERE document_id = %s",
            (doc["document_id"],))
    try:
        changed, _ = picked()
        assert changed[OPEN_CLAIM] == "documents changed since the last assessment"
    finally:
        execute("UPDATE doc_store.documents SET ocr_text = %s WHERE document_id = %s",
                (doc["ocr_text"], doc["document_id"]))


def test_the_batch_account_cannot_sign_in_or_review(run_id, monkeypatch):
    monkeypatch.setenv("CLAIMSENSE_DEV_LOGIN", "1")
    assert client.post("/api/v1/dev/login", json={"user_id": "claimsense-batch"}).status_code == 403
    note_id = batch_note(run_id).json()["note"]["note_id"]
    response = client.post(f"/api/v1/claims/{OPEN_CLAIM}/notes/{note_id}/review",
                           json={"decision": "confirmed"}, headers=BATCH)
    assert response.status_code == 403
