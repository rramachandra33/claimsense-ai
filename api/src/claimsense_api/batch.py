"""The scheduled batch assessment's view of the claims (decided 2026-11-04).

Which open claims need an assessment: those never assessed, and those whose documents changed
since their last assessment. A change is detected with a fingerprint of the claim's documents
(id, OCR status and a hash of the text: SQL function claimsense.documents_fingerprint), stored on
each assessment when its note is written. The documents table belongs to the client's document
store and has no "last updated" time, so the fingerprint needs no change to it.
"""
from .access import OPEN_STATUSES
from .db import fetch_all, fetch_one


def documents_fingerprint(claim_id):
    """The current fingerprint of one claim's documents."""
    return fetch_one("SELECT claimsense.documents_fingerprint(%s) AS fp", (claim_id,))["fp"]


def candidates(limit):
    """Open claims that need an assessment, never-assessed first. Returns (up to `limit` claims,
    how many need one in all). Each: claim_id, assigned adjuster, status and why it was picked."""
    rows = fetch_all("""
        WITH latest AS (
            SELECT DISTINCT ON (claim_id) claim_id, documents_fingerprint
              FROM claimsense.assessments
             ORDER BY claim_id, created_at DESC)
        SELECT c.claim_id, c.assigned_adjuster, c.claim_status,
               l.claim_id IS NULL AS never_assessed,
               l.documents_fingerprint IS DISTINCT FROM claimsense.documents_fingerprint(c.claim_id) AS changed
          FROM claims_mgmt.claims c
          LEFT JOIN latest l USING (claim_id)
         WHERE c.claim_status = ANY(%s)
         ORDER BY (l.claim_id IS NULL) DESC, c.claim_id""", (list(OPEN_STATUSES),))
    picked = []
    for row in rows:
        if row["never_assessed"]:
            reason = "never assessed"
        elif row["changed"]:
            reason = "documents changed since the last assessment"
        else:
            continue
        picked.append({"claim_id": row["claim_id"], "assigned_adjuster": row["assigned_adjuster"],
                       "claim_status": row["claim_status"], "reason": reason})
    return picked[:limit], len(picked)


def spent_today_usd():
    """What batch runs have cost today (UTC), from the usage recorded on their assessments."""
    row = fetch_one("""SELECT coalesce(sum((agent_outputs -> 'usage' ->> 'cost_usd')::numeric), 0) AS spent
                         FROM claimsense.assessments
                        WHERE trigger = 'batch' AND created_at >= date_trunc('day', now())""")
    return float(row["spent"])
