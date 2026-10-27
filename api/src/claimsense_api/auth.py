"""Token check: who is calling? (Ported from the sample's auth.ts.)

For now the API accepts signed development tokens with the same fields Amazon Cognito puts in
an access token (sub, cognito:groups, iss, exp). Switching to real Cognito tokens later changes
only how the signature is checked, not the rest of the code (open question 9).

Identity comes only from the verified token, never from the request body or a typed user id.
"""
import os
import time

import jwt

from .db import fetch_one

DEV_ISSUER = "claimsense-dev"
TOKEN_LIFETIME_SECONDS = 8 * 60 * 60


def jwt_secret():
    secret = os.environ.get("CLAIMSENSE_JWT_SECRET")
    if not secret:
        raise RuntimeError("CLAIMSENSE_JWT_SECRET is not set (see api/.env.example)")
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


def verify_token(token):
    """Check signature, expiry and issuer. Only HS256 is accepted (never 'none')."""
    try:
        return jwt.decode(token, jwt_secret(), algorithms=["HS256"], issuer=DEV_ISSUER,
                          options={"require": ["sub", "exp", "iss"]})
    except jwt.ExpiredSignatureError:
        raise AuthError("token expired")
    except jwt.InvalidTokenError as e:
        raise AuthError(f"invalid token: {e}")


def get_user(authorization_header):
    """Return the calling user as a dict, or raise AuthError / InactiveUser."""
    claims = verify_token(read_bearer_token(authorization_header))
    user = fetch_one("SELECT user_id, full_name, user_group, status FROM claimsense.users "
                     "WHERE user_id = %s", (claims["sub"],))
    if user is None:
        raise AuthError("unknown user")
    token_groups = claims.get("cognito:groups") or []
    token_group = token_groups[0] if token_groups else None
    if token_group != user["user_group"]:
        raise AuthError("token group does not match the user record")
    if user["status"] != "active":
        raise InactiveUser(f"user is {user['status']}")
    return user
