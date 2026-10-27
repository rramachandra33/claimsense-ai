"""On-behalf-of (OBO) tokens for agents (docs/ClaimSense-AI-OBO-Agent-Permissions.pdf).

Agents hold no permissions of their own. For each run, pipeline code asks for one short-lived
token per agent: it acts for the adjuster who started the run, for one claim and one run only,
with only that agent's scopes. Agents can never list claims, write notes or mint more tokens.
"""
import time
import uuid

import jwt

from .auth import OBO_ISSUER, jwt_secret

OBO_LIFETIME_SECONDS = 5 * 60

# What each agent may do. Routes check these scopes (see main.py).
AGENT_SCOPES = {
    "reader": ["claim:read", "documents:read"],
    "coverage": ["claim:read", "policy:read", "clauses:search"],
    "risk": ["claim:read", "documents:read"],
    "drafter": ["claim:read"],
}


def make_obo_token(user, claim_id, agent, run_id, expires_in=OBO_LIFETIME_SECONDS):
    """Issue an OBO token. The caller (main.py) has already checked the user may read the claim."""
    now = int(time.time())
    claims = {
        "sub": user["user_id"],                                  # whose authority
        "cognito:groups": [user["user_group"]] if user["user_group"] else [],
        "act": {"sub": f"claimsense-agent-{agent}", "agent": agent},   # who is acting
        "claim_id": claim_id,                                    # bound to one claim
        "run_id": run_id,                                        # and one pipeline run
        "scope": " ".join(AGENT_SCOPES[agent]),
        "iss": OBO_ISSUER,
        "token_use": "obo",
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + expires_in,
    }
    return jwt.encode(claims, jwt_secret(), algorithm="HS256")

