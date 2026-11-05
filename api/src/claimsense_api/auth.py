"""Token check: who is calling? (Ported from the sample's auth.ts.)

Three kinds of token, told apart by their issuer (iss):
  * Amazon Cognito access tokens (people signing in to the console), signed by Cognito with RS256
    and checked against the pool's public keys. On when CLAIMSENSE_COGNITO_POOL_ID and
    CLAIMSENSE_COGNITO_CLIENT_ID are set (open question 9, decided 2026-11-05).
  * Development tokens (iss claimsense-dev, HS256 with CLAIMSENSE_JWT_SECRET), shaped like a
    Cognito access token. Used by the development sign-in and by the batch service account. Once
    Cognito is on, a person's development token is refused unless CLAIMSENSE_DEV_LOGIN=1.
  * OBO tokens for agents (iss claimsense-obo, see obo.py).

Identity comes only from the verified token, never from the request body or a typed user id.
"""
import json
import os
import time
import urllib.request

import jwt

from .db import fetch_one

DEV_ISSUER = "claimsense-dev"
OBO_ISSUER = "claimsense-obo"          # agent tokens, see obo.py
TOKEN_LIFETIME_SECONDS = 8 * 60 * 60


def jwt_secret():
    secret = os.environ.get("CLAIMSENSE_JWT_SECRET")
    if not secret:
        raise RuntimeError("CLAIMSENSE_JWT_SECRET is not set (see api/.env.example)")
    if len(secret) < 32:
        raise RuntimeError("CLAIMSENSE_JWT_SECRET must be at least 32 characters long")
    return secret


def make_dev_token(user_id, group, expires_in=TOKEN_LIFETIME_SECONDS):
    """Create a signed development token shaped like a Cognito access token."""
    now = int(time.time())
    claims = {
        "sub": user_id,
        "cognito:groups": [group] if group else [],
        "iss": DEV_ISSUER,
        "token_use": "access",
        "iat": now,
        "exp": now + expires_in,
    }
    return jwt.encode(claims, jwt_secret(), algorithm="HS256")


class AuthError(Exception):
    """The caller could not be authenticated (answered with 401)."""


class InactiveUser(Exception):
    """The token is valid but the user may not use the system (answered with 403)."""


def read_bearer_token(authorization_header):
    if not authorization_header:
        raise AuthError("missing token")
    parts = authorization_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise AuthError("malformed Authorization header")
    return parts[1]


# ---------------------------------------------------------------------------
# Amazon Cognito
# ---------------------------------------------------------------------------

_cognito_keys = {}     # the pool's public keys by key id, loaded once


def cognito_settings():
    """(issuer, app client id) when Cognito is configured, else None."""
    pool_id = os.environ.get("CLAIMSENSE_COGNITO_POOL_ID")
    client_id = os.environ.get("CLAIMSENSE_COGNITO_CLIENT_ID")
    if not pool_id or not client_id:
        return None
    region = pool_id.split("_")[0]                     # us-east-1_AbCdEf -> us-east-1
    return f"https://cognito-idp.{region}.amazonaws.com/{pool_id}", client_id


def load_cognito_keys(issuer):
    """The pool's public keys. From CLAIMSENSE_COGNITO_JWKS when set (the Lambda API sits in the
    VPC with no internet, so its deploy stores them there), otherwise from Cognito's JWKS URL."""
    text = os.environ.get("CLAIMSENSE_COGNITO_JWKS")
    if not text:
        with urllib.request.urlopen(issuer + "/.well-known/jwks.json", timeout=5) as response:
            text = response.read().decode()
    keys = {}
    for key in json.loads(text)["keys"]:
        keys[key["kid"]] = jwt.PyJWK(key, algorithm="RS256")
    return keys


def cognito_key(issuer, key_id):
    global _cognito_keys
    if key_id not in _cognito_keys:
        try:
            _cognito_keys = load_cognito_keys(issuer)   # first use, or Cognito rotated its keys
        except Exception as e:
            raise AuthError(f"cannot load the Cognito keys: {e}")
    if key_id not in _cognito_keys:
        raise AuthError("token signed with an unknown Cognito key")
    return _cognito_keys[key_id]


def verify_cognito_token(token, issuer, client_id):
    """A Cognito access token from our app client. Returns the claims with sub = the user name."""
    try:
        key_id = jwt.get_unverified_header(token).get("kid")
        claims = jwt.decode(token, cognito_key(issuer, key_id).key, algorithms=["RS256"],
                            issuer=issuer, options={"require": ["sub", "exp", "iss", "token_use"]})
    except jwt.ExpiredSignatureError:
        raise AuthError("token expired")
    except jwt.InvalidTokenError as e:
        raise AuthError(f"invalid token: {e}")
    if claims["token_use"] != "access":
        raise AuthError("not an access token")          # an ID token is not accepted
    if claims.get("client_id") != client_id:
        raise AuthError("token is for another app client")
    if not claims.get("username"):
        raise AuthError("token has no user name")
    # Cognito's sub is a random id; our users table is keyed by the user name (alice, bob, ...).
    claims["cognito_sub"] = claims["sub"]
    claims["sub"] = claims["username"]
    return claims


def dev_tokens_for_people():
    """Development tokens may stand for a person only while Cognito is off, or the development
    sign-in is deliberately on (local work). The batch service account always uses one."""
    return cognito_settings() is None or os.environ.get("CLAIMSENSE_DEV_LOGIN") == "1"


def verify_token(token):
    """Check signature, expiry and issuer. The issuer decides the one algorithm allowed: RS256
    for Cognito, HS256 for our own tokens (never 'none', never a mix)."""
    cognito = cognito_settings()
    try:
        issuer = jwt.decode(token, options={"verify_signature": False}).get("iss")
    except jwt.InvalidTokenError as e:
        raise AuthError(f"invalid token: {e}")
    if cognito and issuer == cognito[0]:
        return verify_cognito_token(token, *cognito)
    try:
        claims = jwt.decode(token, jwt_secret(), algorithms=["HS256"],
                            options={"require": ["sub", "exp", "iss"]})
    except jwt.ExpiredSignatureError:
        raise AuthError("token expired")
    except jwt.InvalidTokenError as e:
        raise AuthError(f"invalid token: {e}")
    if claims["iss"] not in (DEV_ISSUER, OBO_ISSUER):
        raise AuthError("unknown token issuer")
    return claims


def obo_details(claims):
    """The agent fields of an OBO token, or None for an ordinary user token."""
    if claims["iss"] != OBO_ISSUER:
        return None
    return {
        "agent": claims["act"]["agent"],
        "claim_id": claims["claim_id"],
        "run_id": claims["run_id"],
        "scopes": claims["scope"].split(),
    }


def get_user(authorization_header):
    """Return the calling user as a dict, or raise AuthError / InactiveUser.

    With an OBO token the user is still the human the agent acts for (so a suspended adjuster
    stops their agents too), and user["obo"] holds the agent, claim, run and scopes.
    """
    claims = verify_token(read_bearer_token(authorization_header))
    user = fetch_one("SELECT user_id, full_name, user_group, status FROM claimsense.users "
                     "WHERE user_id = %s", (claims["sub"],))
    if user is None:
        raise AuthError("unknown user")
    if claims["iss"] == DEV_ISSUER and not dev_tokens_for_people() and user["user_group"] != "batch-service":
        raise AuthError("development tokens are off for people: sign in with Cognito")
    token_groups = claims.get("cognito:groups") or []
    token_group = token_groups[0] if token_groups else None
    if token_group != user["user_group"]:
        raise AuthError("token group does not match the user record")
    if user["status"] != "active":
        raise InactiveUser(f"user is {user['status']}")
    user["obo"] = obo_details(claims)
    return user
