"""Platform tests: the rate limit and the AWS Lambda entry point (run `make up` first).

    cd api && uv run --extra dev pytest -q
"""
import json
import os

os.environ.setdefault("CLAIMSENSE_JWT_SECRET", "test-secret-for-pytest-only-0123456789abcdef")

import psycopg  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from claimsense_api.auth import make_dev_token  # noqa: E402
from claimsense_api.db import db_url, execute, fetch_one  # noqa: E402
from claimsense_api.lambda_handler import handler  # noqa: E402
from claimsense_api.main import app  # noqa: E402

try:
    psycopg.connect(db_url()).close()
except psycopg.OperationalError:
    pytest.skip("database not running (run `make up`)", allow_module_level=True)

client = TestClient(app)


def bearer(user_id, group):
    return {"Authorization": "Bearer " + make_dev_token(user_id, group)}


@pytest.fixture
def limit_of_three(monkeypatch):
    """Set the limit to 3 requests a minute, starting from a clean count for alice and david."""
    monkeypatch.setenv("CLAIMSENSE_RATE_LIMIT_PER_MINUTE", "3")
    execute("DELETE FROM claimsense.rate_limit WHERE user_id IN ('alice', 'david')")
    yield
    execute("DELETE FROM claimsense.rate_limit WHERE user_id IN ('alice', 'david')")


def test_requests_over_the_limit_are_refused_and_audited(limit_of_three):
    alice = bearer("alice", "adjuster")
    for _ in range(3):
        assert client.get("/api/v1/claims/CLM-2024-1800", headers=alice).status_code == 200
    response = client.get("/api/v1/claims/CLM-2024-1800", headers=alice)
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"
    assert "claim" not in response.json()
    row = fetch_one("""SELECT decision, reason FROM claimsense.audit_log
                       WHERE user_id = 'alice' ORDER BY audit_id DESC LIMIT 1""")
    assert row == {"decision": "deny", "reason": "rate limit"}


def test_the_limit_is_counted_per_user(limit_of_three):
    alice = bearer("alice", "adjuster")
    for _ in range(4):
        client.get("/api/v1/me", headers=alice)
    assert client.get("/api/v1/me", headers=alice).status_code == 429
    assert client.get("/api/v1/me", headers=bearer("david", "adjuster")).status_code == 200


def test_no_limit_when_it_is_not_set(monkeypatch):
    monkeypatch.delenv("CLAIMSENSE_RATE_LIMIT_PER_MINUTE", raising=False)
    alice = bearer("alice", "adjuster")
    for _ in range(10):
        assert client.get("/api/v1/me", headers=alice).status_code == 200


def function_url_event(method, path, headers=None):
    """A request as a Lambda Function URL delivers it (payload format 2.0)."""
    return {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": path,
        "rawQueryString": "",
        "headers": {"host": "example.lambda-url.us-east-1.on.aws", **(headers or {})},
        "requestContext": {
            "http": {"method": method, "path": path, "protocol": "HTTP/1.1",
                     "sourceIp": "203.0.113.1", "userAgent": "pytest"},
            "domainName": "example.lambda-url.us-east-1.on.aws",
            "requestId": "test", "stage": "$default",
        },
        "isBase64Encoded": False,
    }


def test_lambda_handler_serves_the_same_api():
    response = handler(function_url_event("GET", "/api/v1/health"), None)
    assert response["statusCode"] == 200


def test_lambda_handler_keeps_the_access_rule():
    alice = {"authorization": bearer("alice", "adjuster")["Authorization"]}
    own = handler(function_url_event("GET", "/api/v1/claims/CLM-2024-1800", alice), None)
    assert own["statusCode"] == 200
    assert json.loads(own["body"])["claim"]["claim_id"] == "CLM-2024-1800"
    other = handler(function_url_event("GET", "/api/v1/claims/CLM-2024-1873", alice), None)  # carol's
    assert other["statusCode"] == 403
    assert handler(function_url_event("GET", "/api/v1/claims/CLM-2024-1800"), None)["statusCode"] == 401
