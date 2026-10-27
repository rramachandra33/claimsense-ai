"""ClaimSense data API (FastAPI). Run with:  uvicorn claimsense_api.main:app --port 8000

Every route except /health follows the same three steps, in this order:
  1. who is calling?      -> auth.get_user (token check)
  2. may they see this?   -> access.can_read_claim (the role table)
  3. write the audit row  -> audit.log_audit (allowed and denied alike)
Refusals never say why; the reason goes to the audit log only.
"""
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from .access import can_read_claim
from .audit import log_audit
from .auth import AuthError, InactiveUser, get_user
from .db import fetch_all, fetch_one

app = FastAPI(title="ClaimSense data API", version="0.1.0")

CLAIM_COLUMNS = """claim_id, policy_id, vehicle_vin, vehicle_year, vehicle_make, vehicle_model,
    vehicle_acv_usd, incident_date, incident_type, incident_description, damage_description,
    repair_estimate_usd, injuries_reported, police_report_filed, assigned_adjuster,
    prior_claims_12mo, fraud_risk_score, claim_status, created_at"""


# ---------------------------------------------------------------------------
# Error responses: one shape for every error, { "error": { "code", "message" } }
# ---------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, status, code, message):
        self.status = status
        self.code = code
        self.message = message


@app.exception_handler(ApiError)
def handle_api_error(request: Request, error: ApiError):
    return JSONResponse(status_code=error.status,
                        content={"error": {"code": error.code, "message": error.message}})


def claim_not_available(claim_id):
    # Same answer whether the claim does not exist or the caller may not see it.
    return ApiError(403, "forbidden", f"Claim {claim_id} is not available to you.")


def require_user(authorization, action, resource_type=None, resource_id=None):
    """Step 1 for every route: return the caller, or audit the refusal and stop."""
    try:
        return get_user(authorization)
    except AuthError as e:
        log_audit(action, "deny", resource_type=resource_type, resource_id=resource_id,
                  reason=f"authentication failed: {e}")
        raise ApiError(401, "unauthenticated", "Missing, expired or invalid token.")
    except InactiveUser as e:
        log_audit(action, "deny", resource_type=resource_type, resource_id=resource_id,
                  reason=str(e))
        raise ApiError(403, "forbidden", "Your account may not use this service.")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/v1/health")
def health():
    row = fetch_one("SELECT count(*) AS claims FROM claims_mgmt.claims")
    return {"status": "ok", "claims": row["claims"]}


@app.get("/api/v1/me")
def me(authorization: str = Header(default=None)):
    user = require_user(authorization, "me")
    log_audit("me", "allow", user=user)
    return {"user_id": user["user_id"], "full_name": user["full_name"], "group": user["user_group"]}


@app.get("/api/v1/claims")
def list_claims(authorization: str = Header(default=None)):
    """The work queue: only the claims this caller may read."""
    user = require_user(authorization, "list_claims", "claims")
    all_claims = fetch_all(f"SELECT {CLAIM_COLUMNS} FROM claims_mgmt.claims ORDER BY claim_id")
    visible = []
    for claim in all_claims:
        allowed, reason = can_read_claim(user, claim)
        if allowed:
            visible.append(claim)
    log_audit("list_claims", "allow", user=user, resource_type="claims",
              reason=f"{len(visible)} of {len(all_claims)} claims visible")
    return {"claims": visible, "count": len(visible)}


@app.get("/api/v1/claims/{claim_id}")
def get_claim(claim_id: str, authorization: str = Header(default=None)):
    user = require_user(authorization, "get_claim", "claim", claim_id)
    claim = fetch_one(f"SELECT {CLAIM_COLUMNS} FROM claims_mgmt.claims WHERE claim_id = %s",
                      (claim_id,))
    if claim is None:
        log_audit("get_claim", "deny", user=user, resource_type="claim", resource_id=claim_id,
                  reason="unknown claim")
        raise claim_not_available(claim_id)
    allowed, reason = can_read_claim(user, claim)
    log_audit("get_claim", "allow" if allowed else "deny", user=user, resource_type="claim",
              resource_id=claim_id, reason=reason)
    if not allowed:
        raise claim_not_available(claim_id)
    return {"claim": claim}
