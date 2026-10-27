"""ClaimSense data API (FastAPI). Run with:  uvicorn claimsense_api.main:app --port 8000

Every route except /health follows the same three steps, in this order:
  1. who is calling?      -> auth.get_user (token check)
  2. may they see this?   -> access.can_read_claim (the role table)
  3. write the audit row  -> audit.log_audit (allowed and denied alike)
Refusals never say why; the reason goes to the audit log only.
"""
import os
from uuid import UUID

from fastapi import FastAPI, Header, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .access import can_read_claim
from .audit import log_audit
from .auth import AuthError, InactiveUser, get_user, make_dev_token
from .db import execute, fetch_all, fetch_one
from pydantic import BaseModel

from .notes import NoteError, NoteRequest, check_note, write_note
from .obo import AGENT_SCOPES, OBO_LIFETIME_SECONDS, make_obo_token

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


@app.exception_handler(RequestValidationError)
def handle_bad_request(request: Request, error: RequestValidationError):
    # FastAPI's own body/parameter checks, returned in the same error shape as everything else.
    first = error.errors()[0]
    where = ".".join(str(part) for part in first["loc"][1:])
    return JSONResponse(status_code=400,
                        content={"error": {"code": "invalid_argument", "message": f"{where}: {first['msg']}"}})


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


class DevLoginRequest(BaseModel):
    user_id: str


@app.post("/api/v1/dev/login")
def dev_login(body: DevLoginRequest):
    """Development only: issue a dev token for a known user, so the console can sign in.

    Off unless CLAIMSENSE_DEV_LOGIN=1. In a deployment, Amazon Cognito's sign-in replaces it.
    The usual checks still apply when the token is used (a suspended user is refused then).
    """
    if os.environ.get("CLAIMSENSE_DEV_LOGIN") != "1":
        raise ApiError(404, "not_found", "Not found.")
    user = fetch_one("SELECT user_id, full_name, user_group FROM claimsense.users WHERE user_id = %s",
                     (body.user_id,))
    if user is None:
        log_audit("dev_login", "deny", reason=f"unknown user {body.user_id}")
        raise ApiError(401, "unauthenticated", "Unknown user.")
    log_audit("dev_login", "allow", user=user)
    return {"token": make_dev_token(user["user_id"], user["user_group"]),
            "user_id": user["user_id"], "full_name": user["full_name"], "group": user["user_group"]}


@app.get("/api/v1/me")
def me(authorization: str = Header(default=None)):
    user = require_user(authorization, "me")
    log_audit("me", "allow", user=user)
    return {"user_id": user["user_id"], "full_name": user["full_name"], "group": user["user_group"]}


@app.get("/api/v1/claims")
def list_claims(authorization: str = Header(default=None)):
    """The work queue: only the claims this caller may read."""
    user = require_user(authorization, "list_claims", "claims")
    check_agent(user, "claims:list", "list_claims", resource_type="claims")   # no agent has this scope
    all_claims = fetch_all(f"SELECT {CLAIM_COLUMNS} FROM claims_mgmt.claims ORDER BY claim_id")
    visible = []
    for claim in all_claims:
        allowed, reason = can_read_claim(user, claim)
        if allowed:
            visible.append(claim)
    log_audit("list_claims", "allow", user=user, resource_type="claims",
              reason=f"{len(visible)} of {len(all_claims)} claims visible")
    return {"claims": visible, "count": len(visible)}


def check_agent(user, scope, action, claim_id=None, resource_type="claim"):
    """Extra checks when an agent calls with an OBO token: the scope, and the claim it is bound to.

    Does nothing for a person's own token.
    """
    obo = user["obo"]
    if obo is None:
        return
    if scope not in obo["scopes"]:
        log_audit(action, "deny", user=user, resource_type=resource_type, resource_id=claim_id,
                  reason=f"agent {obo['agent']} lacks scope {scope}")
        raise ApiError(403, "forbidden", "This agent is not allowed to do that.")
    if claim_id is not None and claim_id != obo["claim_id"]:
        log_audit(action, "deny", user=user, resource_type=resource_type, resource_id=claim_id,
                  reason=f"OBO token is bound to {obo['claim_id']}")
        raise claim_not_available(claim_id)


def load_claim_for(user, claim_id, action, scope="claim:read"):
    """Step 2 for every claim-scoped route: return the claim if the user may read it.

    Writes the audit row either way. Unknown and forbidden claims get the same refusal.
    """
    check_agent(user, scope, action, claim_id)
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
    claim = load_claim_for(user, claim_id, "get_policy", scope="policy:read")
    policy = fetch_one(f"SELECT {POLICY_COLUMNS} FROM policy_admin.policies WHERE policy_id = %s",
                       (claim["policy_id"],))
    return {"claim_id": claim_id, "policy": policy}


@app.get("/api/v1/claims/{claim_id}/documents")
def list_documents(claim_id: str, authorization: str = Header(default=None)):
    """The document inventory for a claim (no text here; fetch one document to read it)."""
    user = require_user(authorization, "list_documents", "claim", claim_id)
    load_claim_for(user, claim_id, "list_documents", scope="documents:read")
    documents = fetch_all("""SELECT document_id, document_type, description, upload_date,
                                    page_count, ocr_status
                               FROM doc_store.documents WHERE claim_id = %s
                              ORDER BY document_id""", (claim_id,))
    return {"claim_id": claim_id, "documents": documents, "count": len(documents)}


@app.get("/api/v1/documents/{document_id}")
def get_document(document_id: str, authorization: str = Header(default=None)):
    """One document with its text. The text is null unless OCR is Completed (CLS-DOC-009)."""
    user = require_user(authorization, "get_document", "document", document_id)
    check_agent(user, "documents:read", "get_document", resource_type="document")
    document = fetch_one("""SELECT document_id, claim_id, document_type, description, upload_date,
                                   page_count, ocr_status, ocr_text
                              FROM doc_store.documents WHERE document_id = %s""", (document_id,))
    not_available = ApiError(403, "forbidden", f"Document {document_id} is not available to you.")
    if document is None:
        log_audit("get_document", "deny", user=user, resource_type="document",
                  resource_id=document_id, reason="unknown document")
        raise not_available
    if user["obo"] and document["claim_id"] != user["obo"]["claim_id"]:
        log_audit("get_document", "deny", user=user, resource_type="document", resource_id=document_id,
                  reason=f"OBO token is bound to {user['obo']['claim_id']}")
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
def search_clauses(q: str = "", top_k: int = 4, run_id: UUID | None = None, agent: str = "unspecified",
                   authorization: str = Header(default=None)):
    """Search the policy manual. Only claimsense.clause_index is searched, so a clause the
    load-time guardrail quarantined can never be returned or cited.

    When a pipeline run passes its run_id, the returned clause ids are saved in retrieval_log;
    a draft may later cite only clauses retrieved in its own run."""
    user = require_user(authorization, "search_clauses", "clauses")
    check_agent(user, "clauses:search", "search_clauses", resource_type="clauses")
    if user["obo"]:
        # An agent's searches are always recorded under its own run, whatever the request says.
        run_id = user["obo"]["run_id"]
        agent = user["obo"]["agent"]
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
    if run_id is not None:
        execute("""INSERT INTO claimsense.retrieval_log (run_id, agent, query, clause_ids)
                   VALUES (%s, %s, %s, %s)""", (run_id, agent, q, clause_ids))
    log_audit("search_clauses", "allow", user=user, resource_type="clauses",
              reason=f"{len(clauses)} clause(s) returned", run_id=run_id,
              detail={"query": q, "clause_ids": clause_ids, "agent": agent})
    return {"query": q, "clauses": clauses, "count": len(clauses)}


@app.post("/api/v1/claims/{claim_id}/notes", status_code=201)
def create_note(claim_id: str, note: NoteRequest, authorization: str = Header(default=None),
                idempotency_key: str = Header(default=None)):
    """Save a validated draft decision as an assessment plus an append-only claim note."""
    user = require_user(authorization, "write_note", "claim", claim_id)
    if user["obo"]:
        log_audit("write_note", "deny", user=user, resource_type="claim", resource_id=claim_id,
                  reason="agents may not write notes")
        raise ApiError(403, "forbidden", "This agent is not allowed to do that.")
    load_claim_for(user, claim_id, "write_note")
    if not idempotency_key or len(idempotency_key) > 200:
        raise ApiError(400, "invalid_argument", "An Idempotency-Key header (up to 200 characters) is required.")
    try:
        check_note(note)
        saved, replayed = write_note(user, claim_id, note, idempotency_key)
    except NoteError as e:
        log_audit("write_note", "deny", user=user, resource_type="claim", resource_id=claim_id,
                  reason=f"{e.code}: {e.message}", detail={"run_id": note.run_id})
        raise ApiError(e.status, e.code, e.message)
    log_audit("write_note", "allow", user=user, resource_type="claim_note",
              resource_id=str(saved["note_id"]), run_id=note.run_id,
              reason="idempotent replay" if replayed else "note written",
              detail={"claim_id": claim_id, "outcome": saved["outcome"]})
    if replayed:
        return JSONResponse(status_code=200, headers={"Idempotent-Replay": "true"},
                            content={"note": jsonable_encoder(saved), "idempotent_replay": True})
    return {"note": saved, "idempotent_replay": False}


class OboRequest(BaseModel):
    claim_id: str
    agent: str
    run_id: UUID


@app.get("/api/v1/claims/{claim_id}/notes")
def list_notes(claim_id: str, authorization: str = Header(default=None)):
    """The claim's ClaimSense notes, newest first, each with its full assessment.

    Anyone who may read the claim may read its notes. Agents may not: they never need past drafts.
    """
    user = require_user(authorization, "list_notes", "claim", claim_id)
    if user["obo"]:
        log_audit("list_notes", "deny", user=user, resource_type="claim", resource_id=claim_id,
                  reason="agents may not read notes")
        raise ApiError(403, "forbidden", "This agent is not allowed to do that.")
    load_claim_for(user, claim_id, "list_notes")
    notes = fetch_all("""SELECT n.note_id, n.claim_id, n.on_behalf_of, n.outcome, n.summary,
                                n.cited_clauses, n.deny_reason, n.status, n.author, n.created_at,
                                a.run_id, a.decision_source, a.code_facts, a.agent_outputs, a.models
                           FROM claims_mgmt.claim_notes n
                           JOIN claimsense.assessments a USING (assessment_id)
                          WHERE n.claim_id = %s
                          ORDER BY n.note_id DESC""", (claim_id,))
    return {"claim_id": claim_id, "notes": notes, "count": len(notes)}


@app.post("/api/v1/obo/token")
def issue_obo_token(body: OboRequest, authorization: str = Header(default=None)):
    """Pipeline code asks for one agent's token for one claim and run, with the adjuster's token.

    The adjuster must be able to read the claim. Agents cannot call this with their own OBO token.
    """
    user = require_user(authorization, "issue_obo", "claim", body.claim_id)
    if user["obo"]:
        log_audit("issue_obo", "deny", user=user, resource_type="claim", resource_id=body.claim_id,
                  reason="an agent may not mint tokens")
        raise ApiError(403, "forbidden", "This agent is not allowed to do that.")
    if body.agent not in AGENT_SCOPES:
        raise ApiError(400, "invalid_argument", f"agent must be one of {', '.join(AGENT_SCOPES)}.")
    load_claim_for(user, body.claim_id, "issue_obo")
    token = make_obo_token(user, body.claim_id, body.agent, str(body.run_id))
    log_audit("issue_obo", "allow", user=user, resource_type="claim", resource_id=body.claim_id,
              run_id=body.run_id, detail={"agent": body.agent, "scopes": AGENT_SCOPES[body.agent]})
    return {"token": token, "agent": body.agent, "claim_id": body.claim_id,
            "scopes": AGENT_SCOPES[body.agent], "expires_in": OBO_LIFETIME_SECONDS}
