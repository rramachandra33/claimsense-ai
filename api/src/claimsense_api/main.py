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


def load_claim_for(user, claim_id, action):
    """Step 2 for every claim-scoped route: return the claim if the user may read it.

    Writes the audit row either way. Unknown and forbidden claims get the same refusal.
    """
    claim = fetch_one(f"SELECT {CLAIM_COLUMNS} FROM claims_mgmt.claims WHERE claim_id = %s",
                      (claim_id,))
    if claim is None:
        log_audit(action, "deny", user=user, resource_type="claim", resource_id=claim_id,
                  reason="unknown claim")
        raise claim_not_available(claim_id)
    allowed, reason = can_read_claim(user, claim)
    log_audit(action, "allow" if allowed else "deny", user=user, resource_type="claim",
              resource_id=claim_id, reason=reason)
    if not allowed:
        raise claim_not_available(claim_id)
    return claim


@app.get("/api/v1/claims/{claim_id}")
def get_claim(claim_id: str, authorization: str = Header(default=None)):
    user = require_user(authorization, "get_claim", "claim", claim_id)
    claim = load_claim_for(user, claim_id, "get_claim")
    return {"claim": claim}


# Holder names stay in policy administration: this column list leaves them out on purpose.
POLICY_COLUMNS = """policy_id, vehicle_vin, vehicle_year, vehicle_make, vehicle_model, vehicle_acv_usd,
    coverage_type, collision_coverage, comprehensive_coverage, collision_deductible_usd,
    comprehensive_deductible_usd, liability_limit, medpay_limit_usd, policy_status,
    policy_start, policy_end"""


@app.get("/api/v1/claims/{claim_id}/policy")
def get_policy(claim_id: str, authorization: str = Header(default=None)):
    """The policy is read through a claim the caller may read, so policy ids cannot be browsed."""
    user = require_user(authorization, "get_policy", "claim", claim_id)
    claim = load_claim_for(user, claim_id, "get_policy")
    policy = fetch_one(f"SELECT {POLICY_COLUMNS} FROM policy_admin.policies WHERE policy_id = %s",
                       (claim["policy_id"],))
    return {"claim_id": claim_id, "policy": policy}


@app.get("/api/v1/claims/{claim_id}/documents")
def list_documents(claim_id: str, authorization: str = Header(default=None)):
    """The document inventory for a claim (no text here; fetch one document to read it)."""
    user = require_user(authorization, "list_documents", "claim", claim_id)
    load_claim_for(user, claim_id, "list_documents")
    documents = fetch_all("""SELECT document_id, document_type, description, upload_date,
                                    page_count, ocr_status
                               FROM doc_store.documents WHERE claim_id = %s
                              ORDER BY document_id""", (claim_id,))
    return {"claim_id": claim_id, "documents": documents, "count": len(documents)}


@app.get("/api/v1/documents/{document_id}")
def get_document(document_id: str, authorization: str = Header(default=None)):
    """One document with its text. The text is null unless OCR is Completed (CLS-DOC-009)."""
    user = require_user(authorization, "get_document", "document", document_id)
    document = fetch_one("""SELECT document_id, claim_id, document_type, description, upload_date,
                                   page_count, ocr_status, ocr_text
                              FROM doc_store.documents WHERE document_id = %s""", (document_id,))
    not_available = ApiError(403, "forbidden", f"Document {document_id} is not available to you.")
    if document is None:
        log_audit("get_document", "deny", user=user, resource_type="document",
                  resource_id=document_id, reason="unknown document")
        raise not_available
    claim = fetch_one(f"SELECT {CLAIM_COLUMNS} FROM claims_mgmt.claims WHERE claim_id = %s",
                      (document["claim_id"],))
    allowed, reason = can_read_claim(user, claim)
    log_audit("get_document", "allow" if allowed else "deny", user=user, resource_type="document",
              resource_id=document_id, reason=reason, detail={"claim_id": document["claim_id"]})
    if not allowed:
        raise not_available
    return {"document": document}


@app.get("/api/v1/clauses")
def search_clauses(q: str = "", top_k: int = 4, authorization: str = Header(default=None)):
    """Search the policy manual. Only claimsense.clause_index is searched, so a clause the
    load-time guardrail quarantined can never be returned or cited."""
    user = require_user(authorization, "search_clauses", "clauses")
    q = q.strip()
    if len(q) < 3 or len(q) > 500:
        raise ApiError(400, "invalid_argument", "q must be between 3 and 500 characters.")
    if top_k < 1 or top_k > 8:
        raise ApiError(400, "invalid_argument", "top_k must be between 1 and 8.")
    # Match ANY of the query's words (the '&' between words becomes '|'), best matches first.
    clauses = fetch_all("""WITH words AS (
                               SELECT replace(plainto_tsquery('english', %s)::text, '&', '|')::tsquery AS query
                           )
                           SELECT clause_id, title, text,
                                  round(ts_rank(search, words.query)::numeric, 4) AS score
                             FROM claimsense.clause_index, words
                            WHERE search @@ words.query
                            ORDER BY score DESC, clause_id
                            LIMIT %s""", (q, top_k))
    clause_ids = [c["clause_id"] for c in clauses]
    log_audit("search_clauses", "allow", user=user, resource_type="clauses",
              reason=f"{len(clauses)} clause(s) returned", detail={"query": q, "clause_ids": clause_ids})
    return {"query": q, "clauses": clauses, "count": len(clauses)}
