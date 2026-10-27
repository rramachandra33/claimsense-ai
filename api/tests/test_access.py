"""Access tests against the loaded database (run `make up` first).

    cd api && uv run --extra dev pytest -q

Expected results are written out by hand from the access matrix in
docs/ClaimSense-AI-Users-and-Access-Rules.pdf, so the tests check the rule instead of repeating it.
"""
import os

os.environ.setdefault("CLAIMSENSE_JWT_SECRET", "test-secret-for-pytest-only-0123456789abcdef")

import psycopg  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from claimsense_api.auth import make_dev_token  # noqa: E402
from claimsense_api.db import db_url, fetch_one  # noqa: E402
from claimsense_api.main import app  # noqa: E402

try:
    psycopg.connect(db_url()).close()
except psycopg.OperationalError:
    pytest.skip("database not running (run `make up`)", allow_module_level=True)

client = TestClient(app)

GROUPS = {"alice": "adjuster", "david": "adjuster", "bob": "senior-adjuster",
          "carol": "fraud-investigator", "eve": "total-loss-appraiser",
          "frank": "adjuster", "svc-pipeline": None}

ALL_CLAIMS = {
    "CLM-2024-1800", "CLM-2024-1873", "CLM-2024-1946", "CLM-2024-2019", "CLM-2024-2092",
    "CLM-2024-2165", "CLM-2024-2238", "CLM-2024-2311", "CLM-2024-2384", "CLM-2024-2457",
    "CLM-2024-2530", "CLM-2024-2603", "CLM-2024-2676", "CLM-2024-2749", "CLM-2024-2822",
    "CLM-2024-2895", "CLM-2024-2968", "CLM-2024-3041", "CLM-2024-3114", "CLM-2024-3187",
}

# Claims each active user may read (from the access matrix).
EXPECTED_VISIBLE = {
    "alice": {"CLM-2024-1800", "CLM-2024-2092", "CLM-2024-2165", "CLM-2024-2384",
              "CLM-2024-2749", "CLM-2024-3041"},
    "david": {"CLM-2024-2019", "CLM-2024-2238", "CLM-2024-2311", "CLM-2024-2530",
              "CLM-2024-2822", "CLM-2024-2895"},
    "bob": ALL_CLAIMS,
    "carol": {"CLM-2024-1873", "CLM-2024-2603", "CLM-2024-2968"},
    "eve": {"CLM-2024-1946", "CLM-2024-3187", "CLM-2024-2457", "CLM-2024-3114"},
    "svc-pipeline": set(),
}


def auth_header(user_id):
    return {"Authorization": "Bearer " + make_dev_token(user_id, GROUPS[user_id])}


@pytest.mark.parametrize("user_id", sorted(EXPECTED_VISIBLE))
def test_queue_shows_only_entitled_claims(user_id):
    response = client.get("/api/v1/claims", headers=auth_header(user_id))
    assert response.status_code == 200
    visible = {c["claim_id"] for c in response.json()["claims"]}
    assert visible == EXPECTED_VISIBLE[user_id]


@pytest.mark.parametrize("user_id", sorted(EXPECTED_VISIBLE))
def test_every_claim_matches_the_matrix(user_id):
    """The full 7-user x 20-claim matrix, one request per cell (frank is tested separately)."""
    for claim_id in sorted(ALL_CLAIMS):
        response = client.get(f"/api/v1/claims/{claim_id}", headers=auth_header(user_id))
        expected = 200 if claim_id in EXPECTED_VISIBLE[user_id] else 403
        assert response.status_code == expected, f"{user_id} on {claim_id}"


def test_two_user_test_on_the_same_claim():
    alice = client.get("/api/v1/claims/CLM-2024-1873", headers=auth_header("alice"))
    bob = client.get("/api/v1/claims/CLM-2024-1873", headers=auth_header("bob"))
    assert alice.status_code == 403
    assert "claim" not in alice.json()           # no claim data in a refusal
    assert bob.status_code == 200
    assert bob.json()["claim"]["claim_id"] == "CLM-2024-1873"


def test_unknown_claim_looks_the_same_as_a_forbidden_one():
    unknown = client.get("/api/v1/claims/CLM-2099-0001", headers=auth_header("alice"))
    forbidden = client.get("/api/v1/claims/CLM-2024-1873", headers=auth_header("alice"))
    assert unknown.status_code == forbidden.status_code == 403
    assert unknown.json()["error"]["code"] == forbidden.json()["error"]["code"] == "forbidden"
    assert "carol" not in forbidden.text         # never names who owns the claim


def test_suspended_user_is_refused():
    response = client.get("/api/v1/claims", headers=auth_header("frank"))
    assert response.status_code == 403


@pytest.mark.parametrize("header", [
    {},                                                   # no token
    {"Authorization": "Bearer not-a-token"},              # garbage
    {"Authorization": "Basic YWxpY2U6cGFzcw=="},          # wrong scheme
])
def test_missing_or_bad_token_is_401(header):
    assert client.get("/api/v1/claims", headers=header).status_code == 401


def test_expired_and_forged_tokens_are_401():
    expired = make_dev_token("alice", "adjuster", expires_in=-60)
    assert client.get("/api/v1/claims", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    # A token claiming to be bob, but with alice's group, does not match the user record.
    forged = make_dev_token("bob", "adjuster")
    assert client.get("/api/v1/claims", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_refusals_are_audited_with_the_reason():
    client.get("/api/v1/claims/CLM-2024-1873", headers=auth_header("alice"))
    row = fetch_one("""SELECT decision, reason FROM claimsense.audit_log
                       WHERE user_id = 'alice' AND action = 'get_claim' AND resource_id = 'CLM-2024-1873'
                       ORDER BY audit_id DESC LIMIT 1""")
    assert row["decision"] == "deny"
    assert "carol" in row["reason"]              # the full reason is kept, but only in the audit log
