"""The access rule: may this user read this claim? (Ported from the sample's scope.ts.)

Decided in code, before any agent runs; never by a model. Follows the role table confirmed for
open question 8 (docs/ClaimSense-AI-Users-and-Access-Rules.pdf).
"""
from decimal import Decimal

FRAUD_QUEUE_SCORE = Decimal("0.70")   # provisional threshold (open question 6)
# The scheduled batch assessment reads open claims only (decided 2026-11-04).
OPEN_STATUSES = ("Pending Review", "Under Investigation", "Escalated")
TOTAL_LOSS_RATIO = Decimal("0.75")    # CLS-TL-005: repair >= 75% of ACV


def can_read_claim(user, claim):
    """Return (allowed, reason). The reason is for the audit log only, never for the caller."""
    group = user["user_group"]
    if group is None:
        return False, "user has no group"
    if group == "batch-service":
        if claim["claim_status"] in OPEN_STATUSES:
            return True, "batch: open claim"
        return False, f"batch: claim is {claim['claim_status']}, not open"
    if claim["assigned_adjuster"] == user["user_id"]:
        return True, "assigned"
    if group == "senior-adjuster":
        return True, "senior adjuster reads all claims"
    if group == "fraud-investigator" and claim["fraud_risk_score"] >= FRAUD_QUEUE_SCORE:
        return True, "fraud queue (vendor score >= 0.70)"
    if group == "total-loss-appraiser" and is_total_loss_candidate(claim):
        return True, "total-loss queue (repair >= 75% of ACV)"
    return False, f"not entitled (assigned to {claim['assigned_adjuster']})"


def is_total_loss_candidate(claim):
    estimate = claim["repair_estimate_usd"]
    if estimate is None:
        return False
    return estimate >= TOTAL_LOSS_RATIO * claim["vehicle_acv_usd"]
