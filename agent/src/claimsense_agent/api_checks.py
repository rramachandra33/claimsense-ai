"""Evaluation cases that call the data API directly instead of running an assessment.

Each check sends one or more requests a real caller could send (another user, a broken token,
an agent's token used out of bounds, a review the caller may not make) and returns what came
back. The refusals must also be in the audit log. Every request and response is kept in the
result, so the two-user test (milestone 4) is recorded with both requests and both responses.

    check = CHECKS["two_user_same_claim"]
    passed, detail, exchanges = check(Session())
"""
import base64
import json
import time
import uuid
from datetime import datetime, timezone

import httpx
import jwt

from .api import api_url

ALICE_CLAIM = "CLM-2024-1800"      # assigned to alice (adjuster)
CAROL_CLAIM = "CLM-2024-1873"      # assigned to carol, fraud score 0.87: alice may not read it
ALICE_OTHER_CLAIM = "CLM-2024-2092"  # also alice's
DAVID_CLAIM = "CLM-2024-2019"      # assigned to david
BIG_CLAIM = "CLM-2024-2749"        # alice's, used for the review checks
OPEN_CLAIM = "CLM-2024-2165"       # Pending Review: the batch account may read it


def db():
    from claimsense_api import db as database
    return database


def user_token(user_id, group, expires_in=None):
    from claimsense_api.auth import make_dev_token
    if expires_in is None:
        return make_dev_token(user_id, group)
    return make_dev_token(user_id, group, expires_in=expires_in)


def tampered(token, **changes):
    """The token with its payload edited and the original signature kept."""
    header, payload, signature = token.split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    claims.update(changes)
    new_payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"{header}.{new_payload}.{signature}"


class Session:
    """Sends requests to the evaluation's API and keeps a record of each one."""

    def __init__(self):
        self.base = api_url()
        self.exchanges = []
        self.started = datetime.now(timezone.utc)

    def send(self, method, path, who, token=None, body=None, headers=None):
        all_headers = dict(headers or {})
        if token is not None:
            all_headers["Authorization"] = "Bearer " + token
        response = httpx.request(method, self.base + path, headers=all_headers, json=body)
        try:
            answer = response.json()
        except ValueError:
            answer = response.text
        self.exchanges.append({"who": who, "request": f"{method} {path}", "status": response.status_code,
                               "response": shorten(answer)})
        return response.status_code, answer

    def get(self, path, who, token=None, headers=None):
        return self.send("GET", path, who, token, headers=headers)

    def post(self, path, who, token=None, body=None, headers=None):
        return self.send("POST", path, who, token, body=body, headers=headers)

    def obo(self, user_token_, claim_id, agent, run_id=None):
        status, answer = self.post("/api/v1/obo/token", "pipeline", user_token_,
                                   body={"claim_id": claim_id, "agent": agent,
                                         "run_id": run_id or str(uuid.uuid4())})
        if status != 200:
            raise RuntimeError(f"could not get a {agent} token: HTTP {status}")
        return answer["token"]

    def refusal_audited(self, action, resource_id=None):
        """True when the audit log has a deny row for this action since the check started."""
        sql = """SELECT count(*) AS n FROM claimsense.audit_log
                  WHERE action = %s AND decision = 'deny' AND ts >= %s"""
        params = [action, self.started]
        if resource_id is not None:
            sql += " AND resource_id = %s"
            params.append(resource_id)
        return db().fetch_one(sql, params)["n"] > 0


def shorten(answer):
    """Enough of a response to show what came back, without whole claim files in the results."""
    text = json.dumps(answer, default=str)
    return answer if len(text) <= 400 else text[:400] + "…"


def no_claim_data(answer):
    """A refusal carries an error and nothing else: no claim, documents, policy or notes."""
    return isinstance(answer, dict) and set(answer) == {"error"}


def expect(status, wanted, label):
    return [] if status == wanted else [f"{label}: HTTP {status}, expected {wanted}"]


def outcome(problems, ok_detail):
    return (not problems), ("; ".join(problems) if problems else ok_detail)


# ---- access: who may read which claim --------------------------------------------------------

def two_user_same_claim(s):
    """Milestone 4's two-user test: the same claim, its adjuster and another adjuster."""
    path = f"/api/v1/claims/{ALICE_CLAIM}"
    status_a, answer_a = s.get(path, "alice (assigned adjuster)", user_token("alice", "adjuster"))
    status_d, answer_d = s.get(path, "david (another adjuster)", user_token("david", "adjuster"))
    problems = expect(status_a, 200, "alice") + expect(status_d, 403, "david")
    if status_a == 200 and answer_a["claim"]["claim_id"] != ALICE_CLAIM:
        problems.append("alice got a different claim")
    if not no_claim_data(answer_d):
        problems.append("david's refusal carries claim data")
    allowed = db().fetch_one("""SELECT count(*) AS n FROM claimsense.audit_log WHERE action = 'get_claim'
                                  AND decision = 'allow' AND user_id = 'alice' AND resource_id = %s
                                  AND ts >= %s""", (ALICE_CLAIM, s.started))["n"]
    if not allowed:
        problems.append("alice's read is not in the audit log")
    if not s.refusal_audited("get_claim", ALICE_CLAIM):
        problems.append("david's refusal is not in the audit log")
    return outcome(problems, "alice 200 with the claim; david 403 with no claim data; both audited")


def two_user_documents(s):
    path = f"/api/v1/claims/{ALICE_CLAIM}/documents"
    status_a, answer_a = s.get(path, "alice", user_token("alice", "adjuster"))
    status_d, answer_d = s.get(path, "david", user_token("david", "adjuster"))
    problems = expect(status_a, 200, "alice") + expect(status_d, 403, "david")
    if not no_claim_data(answer_d):
        problems.append("david's refusal lists documents")
    if not s.refusal_audited("list_documents", ALICE_CLAIM):
        problems.append("the refusal is not in the audit log")
    return outcome(problems, "alice sees the document list; david is refused and audited")


def no_token(s):
    status, answer = s.get(f"/api/v1/claims/{ALICE_CLAIM}", "no token")
    problems = expect(status, 401, "no token")
    if not no_claim_data(answer):
        problems.append("the refusal carries claim data")
    if not s.refusal_audited("get_claim", ALICE_CLAIM):
        problems.append("the refusal is not in the audit log")
    return outcome(problems, "401, audited")


def tampered_token(s):
    token = tampered(user_token("alice", "adjuster"), sub="bob", **{"cognito:groups": ["senior-adjuster"]})
    status, answer = s.get(f"/api/v1/claims/{CAROL_CLAIM}", "alice's token edited to say bob", token)
    problems = expect(status, 401, "edited token")
    if not no_claim_data(answer):
        problems.append("the refusal carries claim data")
    if not s.refusal_audited("get_claim", CAROL_CLAIM):
        problems.append("the refusal is not in the audit log")
    return outcome(problems, "an edited token fails the signature check: 401, audited")


def wrong_secret(s):
    now = int(time.time())
    claims = {"sub": "bob", "cognito:groups": ["senior-adjuster"], "iss": "claimsense-dev",
              "token_use": "access", "iat": now, "exp": now + 600}
    token = jwt.encode(claims, "an-attacker-chosen-secret-that-is-long-enough", algorithm="HS256")
    status, _ = s.get(f"/api/v1/claims/{CAROL_CLAIM}", "token signed with another key", token)
    problems = expect(status, 401, "forged token")
    if not s.refusal_audited("get_claim", CAROL_CLAIM):
        problems.append("the refusal is not in the audit log")
    return outcome(problems, "a token signed with another key: 401, audited")


def alg_none(s):
    now = int(time.time())
    claims = {"sub": "bob", "cognito:groups": ["senior-adjuster"], "iss": "claimsense-dev",
              "token_use": "access", "iat": now, "exp": now + 600}
    token = jwt.encode(claims, None, algorithm="none")
    status, _ = s.get(f"/api/v1/claims/{CAROL_CLAIM}", "unsigned token (alg none)", token)
    problems = expect(status, 401, "unsigned token")
    if not s.refusal_audited("get_claim", CAROL_CLAIM):
        problems.append("the refusal is not in the audit log")
    return outcome(problems, "an unsigned token: 401, audited")


def expired_user_token(s):
    token = user_token("alice", "adjuster", expires_in=-60)
    status, _ = s.get(f"/api/v1/claims/{ALICE_CLAIM}", "alice, expired token", token)
    problems = expect(status, 401, "expired token")
    if not s.refusal_audited("get_claim", ALICE_CLAIM):
        problems.append("the refusal is not in the audit log")
    return outcome(problems, "an expired token: 401, audited")


def group_mismatch(s):
    token = user_token("alice", "senior-adjuster")      # validly signed, but alice is an adjuster
    status, _ = s.get(f"/api/v1/claims/{CAROL_CLAIM}", "alice claiming the senior-adjuster group", token)
    problems = expect(status, 401, "wrong group")
    if not s.refusal_audited("get_claim", CAROL_CLAIM):
        problems.append("the refusal is not in the audit log")
    return outcome(problems, "a group the user record does not have: 401, audited")


def unknown_user(s):
    status, _ = s.get(f"/api/v1/claims/{ALICE_CLAIM}", "mallory (not a user)", user_token("mallory", "adjuster"))
    problems = expect(status, 401, "unknown user")
    if not s.refusal_audited("get_claim", ALICE_CLAIM):
        problems.append("the refusal is not in the audit log")
    return outcome(problems, "a user who is not in the users table: 401, audited")


def unknown_claim_same_answer(s):
    """A claim that does not exist and one alice may not read get the same answer, so a caller
    cannot learn which claim ids exist."""
    alice = user_token("alice", "adjuster")
    status_u, answer_u = s.get("/api/v1/claims/CLM-2099-0001", "alice, a claim that does not exist", alice)
    status_f, answer_f = s.get(f"/api/v1/claims/{CAROL_CLAIM}", "alice, someone else's claim", alice)
    problems = expect(status_u, 403, "unknown claim") + expect(status_f, 403, "forbidden claim")
    if status_u == status_f == 403:
        same_code = answer_u["error"]["code"] == answer_f["error"]["code"]
        same_text = (answer_u["error"]["message"].replace("CLM-2099-0001", "X")
                     == answer_f["error"]["message"].replace(CAROL_CLAIM, "X"))
        if not (same_code and same_text):
            problems.append("the two refusals differ, so they reveal which claim exists")
    return outcome(problems, "unknown and forbidden claims get the same 403")


def path_traversal(s):
    alice = user_token("alice", "adjuster")
    problems = []
    for path in (f"/api/v1/claims/{ALICE_CLAIM}%2F..%2F{CAROL_CLAIM}",
                 f"/api/v1/claims/..%2F{CAROL_CLAIM}",
                 f"/api/v1/claims/{CAROL_CLAIM}%00"):
        status, answer = s.get(path, "alice, an encoded path", alice)
        if status == 200 or (isinstance(answer, dict) and "claim" in answer):
            problems.append(f"{path} answered {status} with claim data")
    return outcome(problems, "encoded paths never reach another claim")


def acting_as_ignored(s):
    """Identity comes only from the token: naming another user in the request changes nothing."""
    alice = user_token("alice", "adjuster")
    status, answer = s.get(f"/api/v1/claims/{CAROL_CLAIM}?acting_as=bob&user_id=bob",
                           "alice, asking to act as bob", alice,
                           headers={"X-Acting-As": "bob", "X-User-Id": "bob"})
    problems = expect(status, 403, "acting as bob")
    if not no_claim_data(answer):
        problems.append("the refusal carries claim data")
    row = db().fetch_one("""SELECT user_id FROM claimsense.audit_log WHERE action = 'get_claim'
                              AND resource_id = %s AND ts >= %s ORDER BY audit_id DESC LIMIT 1""",
                         (CAROL_CLAIM, s.started))
    if not row or row["user_id"] != "alice":
        problems.append("the audit log does not name alice as the caller")
    return outcome(problems, "acting_as and X-Acting-As are ignored; audited as alice")


# ---- cross-record leakage: nothing from another claim ----------------------------------------

def a_document_of(claim_id):
    return db().fetch_one("SELECT document_id FROM doc_store.documents WHERE claim_id = %s "
                          "ORDER BY document_id LIMIT 1", (claim_id,))["document_id"]


def obo_document_other_claim(s):
    reader = s.obo(user_token("alice", "adjuster"), ALICE_CLAIM, "reader")
    document = a_document_of(CAROL_CLAIM)
    status, answer = s.get(f"/api/v1/documents/{document}", "reader agent for CLM-2024-1800", reader)
    problems = expect(status, 403, "another claim's document")
    if not no_claim_data(answer):
        problems.append("the refusal carries document text")
    if not s.refusal_audited("get_document", document):
        problems.append("the refusal is not in the audit log")
    return outcome(problems, "the reader's token cannot open another claim's document")


def obo_documents_list_other_claim(s):
    reader = s.obo(user_token("alice", "adjuster"), ALICE_CLAIM, "reader")
    status, answer = s.get(f"/api/v1/claims/{ALICE_OTHER_CLAIM}/documents",
                           "reader agent for CLM-2024-1800", reader)
    problems = expect(status, 403, "another claim's document list")
    if not no_claim_data(answer):
        problems.append("the refusal lists documents")
    if not s.refusal_audited("list_documents", ALICE_OTHER_CLAIM):
        problems.append("the refusal is not in the audit log")
    return outcome(problems, "bound to one claim, even another claim alice herself may read")


def obo_policy_other_claim(s):
    coverage = s.obo(user_token("alice", "adjuster"), ALICE_CLAIM, "coverage")
    status, answer = s.get(f"/api/v1/claims/{ALICE_OTHER_CLAIM}/policy", "coverage agent for CLM-2024-1800",
                           coverage)
    problems = expect(status, 403, "another claim's policy")
    if not no_claim_data(answer):
        problems.append("the refusal carries the policy")
    return outcome(problems, "the coverage agent cannot read another claim's policy")


def user_document_other_claim(s):
    document = a_document_of(CAROL_CLAIM)
    status, answer = s.get(f"/api/v1/documents/{document}", "alice", user_token("alice", "adjuster"))
    problems = expect(status, 403, "another adjuster's document")
    if not no_claim_data(answer):
        problems.append("the refusal carries document text")
    if not s.refusal_audited("get_document", document):
        problems.append("the refusal is not in the audit log")
    return outcome(problems, "a document id from another claim is refused and audited")


def queue_only_entitled(s):
    status, answer = s.get("/api/v1/claims", "alice", user_token("alice", "adjuster"))
    problems = expect(status, 200, "alice's queue")
    if status == 200:
        mine = {r["claim_id"] for r in db().fetch_all(
            "SELECT claim_id FROM claims_mgmt.claims WHERE assigned_adjuster = 'alice'")}
        shown = {c["claim_id"] for c in answer["claims"]}
        if shown != mine:
            problems.append(f"queue shows {sorted(shown - mine)} too, or misses {sorted(mine - shown)}")
    return outcome(problems, "alice's queue holds her claims and nothing else")


def notes_other_claim(s):
    status, answer = s.get(f"/api/v1/claims/{CAROL_CLAIM}/notes", "alice", user_token("alice", "adjuster"))
    problems = expect(status, 403, "another claim's notes")
    if not no_claim_data(answer):
        problems.append("the refusal carries notes")
    if not s.refusal_audited("list_notes", CAROL_CLAIM):
        problems.append("the refusal is not in the audit log")
    return outcome(problems, "another claim's notes are refused and audited")


# ---- forced auto-decision: only an adjuster confirms ---------------------------------------

def agent_cannot_review(s):
    drafter = s.obo(user_token("alice", "adjuster"), ALICE_CLAIM, "drafter")
    status, _ = s.post(f"/api/v1/claims/{ALICE_CLAIM}/notes/1/review", "drafter agent", drafter,
                       body={"decision": "confirmed"})
    problems = expect(status, 403, "agent confirming a draft")
    if not s.refusal_audited("review_note"):
        problems.append("the refusal is not in the audit log")
    return outcome(problems, "an agent cannot confirm a draft")


def batch_cannot_review(s):
    batch = user_token("claimsense-batch", "batch-service")
    status, _ = s.post(f"/api/v1/claims/{OPEN_CLAIM}/notes/999999/review", "claimsense-batch", batch,
                       body={"decision": "confirmed"})
    problems = expect(status, 403, "batch account confirming a draft")
    return outcome(problems, "the batch service account cannot confirm a draft")


def investigator_cannot_confirm(s):
    status, _ = s.post(f"/api/v1/claims/{CAROL_CLAIM}/notes/999999/review", "carol (fraud investigator)",
                       user_token("carol", "fraud-investigator"), body={"decision": "confirmed"})
    problems = expect(status, 403, "fraud investigator confirming a draft")
    return outcome(problems, "a fraud investigator reviews but never confirms")


def write_test_note(s, net_payable):
    """A draft on alice's claim, written through the API as the pipeline would (no agents)."""
    run_id = str(uuid.uuid4())
    note = {"run_id": run_id, "outcome": "DENY", "summary": "Evaluation draft for a review check.",
            "deny_reason": "evaluation draft", "decision_source": "deterministic_fallback",
            "code_facts": {"facts": {"net_payable_if_covered_usd": net_payable}}}
    status, answer = s.post(f"/api/v1/claims/{BIG_CLAIM}/notes", "pipeline for alice",
                            user_token("alice", "adjuster"), body=note,
                            headers={"Idempotency-Key": run_id})
    if status != 201:
        raise RuntimeError(f"could not write the test note: HTTP {status}")
    return run_id, answer["note"]["note_id"]


def remove_test_note(run_id):
    from .evaluate import remove_run
    remove_run(run_id)


def senior_required_above_25k(s):
    run_id, note_id = write_test_note(s, 30000)
    try:
        path = f"/api/v1/claims/{BIG_CLAIM}/notes/{note_id}/review"
        status_a, answer_a = s.post(path, "alice (adjuster)", user_token("alice", "adjuster"),
                                    body={"decision": "confirmed"})
        status_b, _ = s.post(path, "bob (senior adjuster)", user_token("bob", "senior-adjuster"),
                             body={"decision": "confirmed"})
    finally:
        remove_test_note(run_id)
    problems = expect(status_a, 403, "adjuster confirming above $25,000") + expect(status_b, 201, "senior adjuster")
    if status_a == 403 and answer_a["error"]["code"] != "senior_required":
        problems.append(f"refused as {answer_a['error']['code']}, expected senior_required")
    return outcome(problems, "above $25,000 net payable only a senior adjuster confirms (CLS-PAY-012)")


def review_once(s):
    run_id, note_id = write_test_note(s, 1000)
    try:
        path = f"/api/v1/claims/{BIG_CLAIM}/notes/{note_id}/review"
        alice = user_token("alice", "adjuster")
        first, _ = s.post(path, "alice", alice, body={"decision": "confirmed"})
        second, _ = s.post(path, "alice again", alice, body={"decision": "rejected", "reason": "changed mind"})
    finally:
        remove_test_note(run_id)
    problems = expect(first, 201, "first review") + expect(second, 409, "second review")
    return outcome(problems, "a review is recorded once and cannot be overwritten")


# ---- agent tokens ---------------------------------------------------------------------------

def agent_cannot_mint(s):
    reader = s.obo(user_token("alice", "adjuster"), ALICE_CLAIM, "reader")
    status, _ = s.post("/api/v1/obo/token", "reader agent", reader,
                       body={"claim_id": ALICE_CLAIM, "agent": "coverage", "run_id": str(uuid.uuid4())})
    problems = expect(status, 403, "agent minting a token")
    if not s.refusal_audited("issue_obo", ALICE_CLAIM):
        problems.append("the refusal is not in the audit log")
    return outcome(problems, "an agent cannot mint tokens")


def agent_cannot_read_notes(s):
    reader = s.obo(user_token("alice", "adjuster"), ALICE_CLAIM, "reader")
    status, _ = s.get(f"/api/v1/claims/{ALICE_CLAIM}/notes", "reader agent", reader)
    problems = expect(status, 403, "agent reading past notes")
    return outcome(problems, "agents never read past drafts")


def obo_of_other_user(s):
    reader = s.obo(user_token("david", "adjuster"), DAVID_CLAIM, "reader")
    status, answer = s.get(f"/api/v1/claims/{ALICE_CLAIM}", "reader agent acting for david", reader)
    problems = expect(status, 403, "david's agent on alice's claim")
    if not no_claim_data(answer):
        problems.append("the refusal carries claim data")
    return outcome(problems, "an agent token for one user and claim does not open another")


def obo_tampered_scope(s):
    reader = s.obo(user_token("alice", "adjuster"), ALICE_CLAIM, "reader")
    widened = tampered(reader, scope="claim:read documents:read policy:read claims:list")
    status, _ = s.get(f"/api/v1/claims/{ALICE_CLAIM}/policy", "reader agent, scope edited", widened)
    problems = expect(status, 401, "edited scope")
    return outcome(problems, "an agent cannot widen its own scopes")


CHECKS = {f.__name__: f for f in (
    two_user_same_claim, two_user_documents, no_token, tampered_token, wrong_secret, alg_none,
    expired_user_token, group_mismatch, unknown_user, unknown_claim_same_answer, path_traversal,
    acting_as_ignored,
    obo_document_other_claim, obo_documents_list_other_claim, obo_policy_other_claim,
    user_document_other_claim, queue_only_entitled, notes_other_claim,
    agent_cannot_review, batch_cannot_review, investigator_cannot_confirm, senior_required_above_25k,
    review_once,
    agent_cannot_mint, agent_cannot_read_notes, obo_of_other_user, obo_tampered_scope,
)}


def run_check(name):
    """Run one check. Returns (passed, detail, exchanges)."""
    session = Session()
    passed, detail = CHECKS[name](session)
    return passed, detail, session.exchanges
