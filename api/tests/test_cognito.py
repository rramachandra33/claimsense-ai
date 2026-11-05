"""Tests for Amazon Cognito access tokens (run `make up` first).

The tests play Cognito's part: they make an RSA key pair, give the API its public half as the
pool's JWKS (CLAIMSENSE_COGNITO_JWKS, as the Lambda deploy does) and sign tokens shaped exactly
like Cognito access tokens with the private half.
"""
import json
import os
import time
import uuid

os.environ.setdefault("CLAIMSENSE_JWT_SECRET", "test-secret-for-pytest-only-0123456789abcdef")

import jwt  # noqa: E402
import psycopg  # noqa: E402
import pytest  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from claimsense_api import auth  # noqa: E402
from claimsense_api.auth import make_dev_token  # noqa: E402
from claimsense_api.db import db_url  # noqa: E402
from claimsense_api.main import app  # noqa: E402

try:
    psycopg.connect(db_url()).close()
except psycopg.OperationalError:
    pytest.skip("database not running (run `make up`)", allow_module_level=True)

client = TestClient(app)
POOL_ID = "us-east-1_TestPool1"
CLIENT_ID = "testclient123"
ISSUER = f"https://cognito-idp.us-east-1.amazonaws.com/{POOL_ID}"
KEY_ID = "test-key-1"
PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def public_jwks(private_key, key_id):
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public.update({"kid": key_id, "alg": "RS256", "use": "sig"})
    return json.dumps({"keys": [public]})


@pytest.fixture(autouse=True)
def cognito_on(monkeypatch):
    monkeypatch.setenv("CLAIMSENSE_COGNITO_POOL_ID", POOL_ID)
    monkeypatch.setenv("CLAIMSENSE_COGNITO_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("CLAIMSENSE_COGNITO_JWKS", public_jwks(PRIVATE_KEY, KEY_ID))
    monkeypatch.delenv("CLAIMSENSE_DEV_LOGIN", raising=False)
    monkeypatch.setattr(auth, "_cognito_keys", {})
    yield


def cognito_token(username, groups, key=PRIVATE_KEY, key_id=KEY_ID, **changes):
    """A token with the fields of a real Cognito access token."""
    now = int(time.time())
    claims = {"sub": str(uuid.uuid4()), "cognito:groups": groups, "iss": ISSUER,
              "client_id": CLIENT_ID, "origin_jti": str(uuid.uuid4()), "event_id": str(uuid.uuid4()),
              "token_use": "access", "scope": "aws.cognito.signin.user.admin", "auth_time": now,
              "exp": now + 3600, "iat": now, "jti": str(uuid.uuid4()), "username": username}
    claims.update(changes)
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": key_id})


def me(token):
    return client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})


# --- accepted -------------------------------------------------------------------

def test_a_cognito_access_token_signs_in_the_user_by_user_name():
    response = me(cognito_token("alice", ["adjuster"]))
    assert response.status_code == 200
    assert response.json()["user_id"] == "alice"


def test_cognito_user_sees_only_their_claims():
    token = cognito_token("alice", ["adjuster"])
    response = client.get("/api/v1/claims", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert len(response.json()["claims"]) == 6


def test_cognito_user_can_get_agent_tokens():
    token = cognito_token("alice", ["adjuster"])
    body = {"claim_id": "CLM-2024-1800", "agent": "reader", "run_id": str(uuid.uuid4())}
    response = client.post("/api/v1/obo/token", json=body, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    agent = {"Authorization": "Bearer " + response.json()["token"]}
    assert client.get("/api/v1/claims/CLM-2024-1800", headers=agent).status_code == 200


# --- refused ----------------------------------------------------------------------

def test_suspended_user_is_refused_even_with_a_valid_cognito_token():
    assert me(cognito_token("frank", ["adjuster"])).status_code == 403


def test_a_user_cognito_knows_but_we_do_not_is_refused():
    assert me(cognito_token("mallory", ["senior-adjuster"])).status_code == 401


def test_cognito_group_must_match_the_user_record():
    # The Cognito group is the role; a pool edit cannot quietly make alice a senior adjuster.
    assert me(cognito_token("alice", ["senior-adjuster"])).status_code == 401


def test_token_signed_by_another_key_is_refused():
    assert me(cognito_token("alice", ["adjuster"], key=OTHER_KEY)).status_code == 401


def test_unknown_key_id_is_refused():
    assert me(cognito_token("alice", ["adjuster"], key=OTHER_KEY, key_id="other")).status_code == 401


def test_expired_token_is_refused():
    assert me(cognito_token("alice", ["adjuster"], exp=int(time.time()) - 60)).status_code == 401


def test_id_token_is_refused():
    assert me(cognito_token("alice", ["adjuster"], token_use="id")).status_code == 401


def test_token_for_another_app_client_is_refused():
    assert me(cognito_token("alice", ["adjuster"], client_id="someone-else")).status_code == 401


def test_token_from_another_pool_is_refused():
    other = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_OtherPool"
    assert me(cognito_token("alice", ["adjuster"], iss=other)).status_code == 401


def test_cognito_issuer_with_our_shared_secret_is_refused():
    # The issuer fixes the algorithm: an HS256 token claiming to be Cognito's is not checked
    # with the shared secret.
    now = int(time.time())
    claims = {"sub": "alice", "username": "alice", "cognito:groups": ["adjuster"], "iss": ISSUER,
              "client_id": CLIENT_ID, "token_use": "access", "iat": now, "exp": now + 600}
    token = jwt.encode(claims, os.environ["CLAIMSENSE_JWT_SECRET"], algorithm="HS256")
    assert me(token).status_code == 401


# --- development tokens once Cognito is on -------------------------------------------

def test_a_persons_development_token_is_refused_once_cognito_is_on():
    assert me(make_dev_token("alice", "adjuster")).status_code == 401


def test_development_tokens_still_work_with_the_development_sign_in_on(monkeypatch):
    monkeypatch.setenv("CLAIMSENSE_DEV_LOGIN", "1")
    assert me(make_dev_token("alice", "adjuster")).status_code == 200


def test_the_batch_service_token_still_works():
    token = make_dev_token("claimsense-batch", "batch-service")
    response = client.get("/api/v1/batch/candidates", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200


def test_development_sign_in_is_off_without_the_switch():
    response = client.post("/api/v1/dev/login", json={"user_id": "alice"})
    assert response.status_code == 404
