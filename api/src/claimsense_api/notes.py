"""The one write-back: a draft decision saved as an assessment plus an append-only claim note.

Rules (open questions 3 and 4):
  * a note cites at least one clause, unless it is a DENY with a reason (e.g. "no supporting clause found")
  * every cited clause must have been returned by clause search in the same run (retrieval_log)
  * retries are safe: the same Idempotency-Key with the same body returns the stored note;
    the same key with a different body is refused with 409

This write is called by pipeline code after validation. It is never offered to agents as a tool.
"""
import hashlib
import json
import uuid

import psycopg
from pydantic import BaseModel

from .db import connect, fetch_all, fetch_one

OUTCOMES = ("APPROVE", "FLAG", "ROUTE", "DENY")


class NoteRequest(BaseModel):
    run_id: str
    outcome: str
    summary: str
    cited_clauses: list[str] = []
    deny_reason: str | None = None
    decision_source: str = "model"
    code_facts: dict = {}
    agent_outputs: dict = {}
    models: dict = {}
    claim_status_at_run: str | None = None


class NoteError(Exception):
    """A rule was broken. status is the HTTP status to answer with."""

    def __init__(self, status, code, message):
        self.status = status
        self.code = code
        self.message = message


def request_hash(claim_id, note):
    """A fingerprint of the request, so a retry can be told apart from a different request."""
    text = json.dumps({"claim_id": claim_id, "note": note.model_dump()}, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def check_note(note):
    """Check the body before touching the database. Raises NoteError."""
    try:
        uuid.UUID(note.run_id)
    except ValueError:
        raise NoteError(400, "invalid_argument", "run_id must be a UUID.")
    if note.outcome not in OUTCOMES:
        raise NoteError(400, "invalid_argument", f"outcome must be one of {', '.join(OUTCOMES)}.")
    # 2000: the draft's summary (at most 600) plus the lines code adds (other signals, pending
    # documentation), which a claim with many signals can make long.
    if not note.summary.strip() or len(note.summary) > 2000:
        raise NoteError(400, "invalid_argument", "summary must be 1 to 2000 characters.")
    if note.decision_source not in ("model", "deterministic_fallback", "agent_failure"):
        raise NoteError(400, "invalid_argument",
                        "decision_source must be model, deterministic_fallback or agent_failure.")
    if not note.cited_clauses:
        if note.outcome != "DENY" or not note.deny_reason:
            raise NoteError(422, "citation_required",
                            "A note must cite clauses, unless it is a DENY with a deny_reason.")


def check_citations_were_retrieved(note):
    """Every cited clause must have come back from clause search in this run."""
    if not note.cited_clauses:
        return
    rows = fetch_all("SELECT clause_ids FROM claimsense.retrieval_log WHERE run_id = %s",
                     (note.run_id,))
    retrieved = set()
    for row in rows:
        retrieved.update(row["clause_ids"])
    not_retrieved = [c for c in note.cited_clauses if c not in retrieved]
    if not_retrieved:
        raise NoteError(422, "citation_not_retrieved",
                        f"Cited clauses were not retrieved in this run: {', '.join(not_retrieved)}.")


def find_previous(user_id, idem_key):
    return fetch_one("""SELECT request_hash, note_id FROM claimsense.idempotency_keys
                        WHERE user_id = %s AND idem_key = %s""", (user_id, idem_key))


def read_note(note_id):
    return fetch_one("SELECT * FROM claims_mgmt.claim_notes WHERE note_id = %s", (note_id,))


def replay_or_conflict(previous, this_hash):
    """Same key seen before: same body -> stored note; different body -> 409."""
    if previous["request_hash"] != this_hash:
        raise NoteError(409, "idempotency_conflict",
                        "This Idempotency-Key was already used with a different request.")
    return read_note(previous["note_id"])


def write_note(user, claim_id, note, idem_key):
    """Save the assessment and the note in one transaction. Returns (note, replayed)."""
    this_hash = request_hash(claim_id, note)

    previous = find_previous(user["user_id"], idem_key)
    if previous:
        return replay_or_conflict(previous, this_hash), True

    check_citations_were_retrieved(note)

    try:
        with connect() as conn:
            assessment = conn.execute(
                """INSERT INTO claimsense.assessments
                     (run_id, claim_id, on_behalf_of, outcome, decision_source, code_facts,
                      agent_outputs, citations, models, claim_status_at_run)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   RETURNING assessment_id""",
                (note.run_id, claim_id, user["user_id"], note.outcome, note.decision_source,
                 json.dumps(note.code_facts), json.dumps(note.agent_outputs), note.cited_clauses,
                 json.dumps(note.models), note.claim_status_at_run),
            ).fetchone()
            saved = conn.execute(
                """INSERT INTO claims_mgmt.claim_notes
                     (claim_id, assessment_id, on_behalf_of, outcome, summary, cited_clauses, deny_reason)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   RETURNING *""",
                (claim_id, assessment["assessment_id"], user["user_id"], note.outcome, note.summary,
                 note.cited_clauses, note.deny_reason),
            ).fetchone()
            conn.execute(
                """INSERT INTO claimsense.idempotency_keys (user_id, idem_key, request_hash, note_id)
                   VALUES (%s, %s, %s, %s)""",
                (user["user_id"], idem_key, this_hash, saved["note_id"]),
            )
        return saved, False
    except psycopg.errors.UniqueViolation:
        # Two requests raced with the same key, or this run was already recorded.
        previous = find_previous(user["user_id"], idem_key)
        if previous:
            return replay_or_conflict(previous, this_hash), True
        raise NoteError(409, "run_already_recorded", "A draft for this run_id was already saved.")


# ---- reviews: an adjuster confirms or rejects a draft (decided 2026-11-04) -------------------

REVIEW_DECISIONS = ("confirmed", "rejected")

# Who may review drafts (open question 8, confirmed 2026-10-26): adjusters and senior adjusters.
# Fraud investigators and total-loss appraisers review only; service accounts never confirm.
REVIEWER_GROUPS = ("adjuster", "senior-adjuster")
SENIOR_CONFIRMATION_ABOVE = 25000      # CLS-PAY-012: above this, only a senior adjuster confirms


class ReviewRequest(BaseModel):
    decision: str
    reason: str | None = None


def review_note(user, claim_id, note_id, review):
    """Record one review of a draft note. Raises NoteError. Returns the review row.

    Rules: only adjusters and senior adjusters review; confirmed or rejected; once per note; a
    rejection needs a reason, and so does any review of an agent-failure DENY (code wrote it because
    an agent could not finish); confirming a draft whose net payable is above $25,000 needs a senior
    adjuster (CLS-PAY-012)."""
    if user["user_group"] not in REVIEWER_GROUPS:
        raise NoteError(403, "forbidden", "Your role may read drafts but not confirm or reject them.")
    if review.decision not in REVIEW_DECISIONS:
        raise NoteError(400, "invalid_argument", "decision must be confirmed or rejected.")
    reason = (review.reason or "").strip() or None
    if reason and len(reason) > 1000:
        raise NoteError(400, "invalid_argument", "reason must be at most 1000 characters.")
    note = fetch_one("""SELECT n.note_id, a.decision_source,
                               (a.code_facts -> 'facts' ->> 'net_payable_if_covered_usd')::numeric AS net_payable
                          FROM claims_mgmt.claim_notes n
                          JOIN claimsense.assessments a USING (assessment_id)
                         WHERE n.note_id = %s AND n.claim_id = %s""", (note_id, claim_id))
    if note is None:
        raise NoteError(404, "not_found", "No such note on this claim.")
    if review.decision == "rejected" and not reason:
        raise NoteError(400, "reason_required", "Give a reason for rejecting the draft.")
    if note["decision_source"] == "agent_failure" and not reason:
        raise NoteError(400, "reason_required",
                        "This DENY was written because an agent could not finish: give the reason for your review.")
    if (review.decision == "confirmed" and note["net_payable"] is not None
            and note["net_payable"] > SENIOR_CONFIRMATION_ABOVE and user["user_group"] != "senior-adjuster"):
        raise NoteError(403, "senior_required",
                        "Net payable is above $25,000: only a senior adjuster may confirm this draft (CLS-PAY-012).")
    try:
        with connect() as conn:
            return conn.execute(
                """INSERT INTO claims_mgmt.note_reviews (note_id, decision, reviewed_by, reason)
                   VALUES (%s, %s, %s, %s) RETURNING *""",
                (note_id, review.decision, user["user_id"], reason),
            ).fetchone()
    except psycopg.errors.UniqueViolation:
        raise NoteError(409, "already_reviewed", "This draft has already been reviewed.")
