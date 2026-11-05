"""Code facts: dates, money and document checks, worked out by code, never by a model.

The rules come from the AutoSure policy manual as written (open question 6). This is the same
logic as `scripts/import_course_fixtures.py`; a test checks both give the same facts for all
20 course claims.

`outcome_signals` lists which outcome each fact points to. When several are signalled, PRECEDENCE
picks the one the note carries (decided 2026-11-04, open question 2): DENY, then FLAG, then ROUTE,
then APPROVE. The others are not dropped: `note_additions` lists them on the note.
"""
import os
import re
from datetime import date
from decimal import Decimal

# CLS-COMP-002: theft, vandalism, fire, flood, falling objects, glass and animal strikes are
# comprehensive; pothole impact is collision. Collision with a vehicle or object, or upset, is
# collision (CLS-COLL-001). Anything not listed maps to None, and code never guesses a deductible.
LOSS_CATEGORY = {
    "Backing accident": "collision", "Hit and run": "collision", "Low-speed collision": "collision",
    "Multi-vehicle pileup": "collision", "Parking lot collision": "collision",
    "Pothole damage": "collision", "Rear-end collision": "collision", "Rear-end on highway": "collision",
    "Rollover": "collision", "Side-swipe": "collision", "Single-vehicle accident": "collision",
    "T-bone collision": "collision", "Underride accident": "collision",
    "Animal strike": "comprehensive", "Carjacking": "comprehensive", "Flood damage": "comprehensive",
    "Garage fire": "comprehensive", "Glass breakage": "comprehensive", "Hail damage": "comprehensive",
    "Storm damage": "comprehensive", "Theft recovery": "comprehensive", "Vandalism": "comprehensive",
}
TOTAL_LOSS_RATIO = Decimal("0.75")            # CLS-TL-005
SENIOR_CONFIRMATION_ABOVE = Decimal("25000")  # CLS-PAY-012
FRAUD_SCORE_THRESHOLD = 0.70                  # provisional (DECISIONS.md)

# Which outcome the note carries when several are signalled: earlier in the list wins.
# Decided 2026-11-04 (open question 2): no cover ends it; fraud review comes before any specialist
# or payment; a specialist comes before payment.
PRECEDENCE = ["DENY", "FLAG", "ROUTE", "APPROVE"]


def to_decimal(value):
    """Money arrives as JSON numbers (24500.0); Decimal(str(...)) keeps it exact."""
    if value is None:
        return None
    return Decimal(str(value))


def to_number(value):
    """A Decimal back to a plain int or float for JSON: 2700, not 2700.00."""
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def compute_facts(claim, policy, documents):
    """The code facts for one claim, from the claim, its policy and its document list."""
    estimate = to_decimal(claim["repair_estimate_usd"])
    acv = to_decimal(claim["vehicle_acv_usd"])
    loss_date = date.fromisoformat(claim["incident_date"])
    start = date.fromisoformat(policy["policy_start"])
    end = date.fromisoformat(policy["policy_end"])
    in_force = start <= loss_date <= end                          # CLS-PER-006, inclusive
    category = LOSS_CATEGORY.get(claim["incident_type"])

    if policy["coverage_type"] == "Liability Only":               # CLS-LIAB-003
        coverage_purchased = False
    elif category == "collision":
        coverage_purchased = policy["collision_coverage"]
    elif category == "comprehensive":
        coverage_purchased = policy["comprehensive_coverage"]
    else:
        coverage_purchased = None

    deductible = None                                             # CLS-DED-004
    if category == "collision":
        deductible = to_decimal(policy["collision_deductible_usd"])
    elif category == "comprehensive":
        deductible = to_decimal(policy["comprehensive_deductible_usd"])

    net = None                                                    # CLS-COLL-001 / CLS-DED-004
    if coverage_purchased and deductible is not None and estimate is not None:
        net = max(min(estimate, acv) - deductible, Decimal(0))

    ratio = None
    if estimate is not None:
        ratio = (estimate / acv).quantize(Decimal("0.0001"))

    by_type = {}
    for doc in documents:
        by_type.setdefault(doc["document_type"], []).append(doc)
    estimates = by_type.get("REPAIR_ESTIMATE", [])
    pending = sorted(doc["document_id"] for doc in documents if doc["ocr_status"] != "Completed")

    return {
        "claim_id": claim["claim_id"],
        "loss_category": category,
        "in_force_at_loss": in_force,
        "days_after_policy_end": max((loss_date - end).days, 0),
        "status_field_conflict": policy["policy_status"] == "Active" and not in_force,
        # Each system keeps its own vehicle record; a mismatch is evidence, not an error.
        "vin_matches_policy": claim["vehicle_vin"] == policy["vehicle_vin"],
        "vehicle_matches_policy": (claim["vehicle_year"] == policy["vehicle_year"]
                                   and claim["vehicle_make"] == policy["vehicle_make"]
                                   and claim["vehicle_model"] == policy["vehicle_model"]),
        "acv_differs_from_policy_usd": to_number(acv - to_decimal(policy["vehicle_acv_usd"])),
        "coverage_purchased_for_loss": coverage_purchased,
        "liability_only_policy": policy["coverage_type"] == "Liability Only",
        "deductible_usd": to_number(deductible) if deductible is not None else None,
        "repair_to_acv_ratio": float(ratio) if ratio is not None else None,
        "total_loss_candidate": ratio is not None and ratio >= TOTAL_LOSS_RATIO,       # CLS-TL-005
        "net_payable_if_covered_usd": to_number(net) if net is not None else None,
        "senior_confirmation_required": net is not None and net > SENIOR_CONFIRMATION_ABOVE,  # CLS-PAY-012
        "documents": {
            "count": len(documents),
            "fnol_count": len(by_type.get("FNOL_FORM", [])),
            "repair_estimate_on_file": len(estimates) > 0,
            "repair_estimate_readable": any(d["ocr_status"] == "Completed" for d in estimates),  # CLS-DOC-009
            "pending_ocr": pending,
            "police_report_on_file": "POLICE_REPORT" in by_type,
            "medical_report_on_no_injury_claim": ("MEDICAL_REPORT" in by_type
                                                  and not claim["injuries_reported"]),  # CLS-INJ-008
        },
        "rule_sources": ["CLS-PER-006", "CLS-LIAB-003", "CLS-COMP-002", "CLS-DED-004", "CLS-COLL-001",
                         "CLS-TL-005", "CLS-PAY-012", "CLS-DOC-009", "CLS-INJ-008"],
    }


def fraud_indicators(claim):
    """The CLS-FRD-007 indicators code can check from the claim record."""
    found = []
    if claim["prior_claims_12mo"] >= 2:
        found.append(f"{claim['prior_claims_12mo']} prior claims in 12 months")
    airbag = "airbag" in claim["damage_description"].lower()
    if not claim["police_report_filed"] and (claim["injuries_reported"] or airbag):
        found.append("no police report with injury or airbag deployment")
    if claim["fraud_risk_score"] >= FRAUD_SCORE_THRESHOLD:
        found.append(f"vendor score {claim['fraud_risk_score']} (0.70 is a provisional threshold)")
    return found


def location_check_on():
    """CLAIMSENSE_LOCATION_CHECK=1 turns on the loss-location check. Off by default: in the course
    data every police report gives a different location from the FNOL."""
    return os.environ.get("CLAIMSENSE_LOCATION_CHECK") == "1"


def loss_location(text):
    """The "Location" line of an FNOL or a police report, or None."""
    match = re.search(r"^Location\s+(.+)$", text or "", re.MULTILINE)
    return match.group(1).strip() if match else None


def locations_match(fnol_text, police_text):
    """False when the FNOL and the police report give different loss locations; None when either
    location is missing."""
    fnol, police = loss_location(fnol_text), loss_location(police_text)
    if fnol is None or police is None:
        return None
    return fnol.lower() == police.lower()


def outcome_signals(claim, facts):
    """Each signal: the outcome it points to, why, and the clause behind it."""
    signals = []
    if not facts["in_force_at_loss"]:
        signals.append({"outcome": "DENY", "clause": "CLS-PER-006",
                        "reason": f"loss {facts['days_after_policy_end']} days after policy end"})
    if facts["coverage_purchased_for_loss"] is False:
        # Liability Only has no own-vehicle cover at all (CLS-LIAB-003); a Full Coverage policy without
        # the cover for this loss falls under that cover's own clause.
        if facts["liability_only_policy"]:
            clause = "CLS-LIAB-003"
        elif facts["loss_category"] == "comprehensive":
            clause = "CLS-COMP-002"
        else:
            clause = "CLS-COLL-001"
        signals.append({"outcome": "DENY", "clause": clause,
                        "reason": f"no {facts['loss_category']} cover on this policy"})
    if facts["total_loss_candidate"]:
        signals.append({"outcome": "ROUTE", "clause": "CLS-TL-005",
                        "reason": f"repair/ACV {facts['repair_to_acv_ratio']} ≥ 0.75, total-loss appraiser"})
    if claim["injuries_reported"]:
        signals.append({"outcome": "ROUTE", "clause": "CLS-INJ-008",
                        "reason": "injury reported, injury-qualified adjuster"})
    if facts["senior_confirmation_required"]:
        signals.append({"outcome": "ROUTE", "clause": "CLS-PAY-012",
                        "reason": f"net payable {facts['net_payable_if_covered_usd']} > 25000, senior adjuster"})
    indicators = fraud_indicators(claim)
    if facts["vin_matches_policy"] is False:
        # Decided 2026-11-04: a claim on a vehicle that is not the one on the policy is a
        # misrepresentation indicator (CLS-FRD-007), reviewed before payment. Only the end of the
        # VIN goes on the note.
        indicators.append(f"the claim's VIN (ending {claim['vehicle_vin'][-6:]}) does not match "
                          "the VIN on the policy")
    if facts.get("loss_locations_match") is False:      # only set when the location check is on
        indicators.append("FNOL and police report give different loss locations")
    if indicators:
        signals.append({"outcome": "FLAG", "clause": "CLS-FRD-007",
                        "reason": "fraud indicators: " + "; ".join(indicators)})
    return signals


def documentation_gaps(facts):
    """Gaps in the file. Whether a gap means FLAG or ROUTE is part of the open precedence question."""
    docs = facts["documents"]
    gaps = []
    if not docs["repair_estimate_readable"]:
        where = "pending OCR" if docs["repair_estimate_on_file"] else "none on file"
        gaps.append({"clause": "CLS-DOC-009", "reason": f"no readable repair estimate ({where})"})
    if docs["medical_report_on_no_injury_claim"]:
        gaps.append({"clause": "CLS-INJ-008", "reason": "medical report on a no-injury FNOL"})
    return gaps


def rule_clauses(facts, signals, gaps):
    """The clauses behind code's own rules for this claim: what an APPROVE rests on (the insuring
    clause, the policy period, the deductible) and the clause behind each signal and gap.

    Pipeline code retrieves these in every run, so a draft can always cite the rules code applied,
    whatever the agents chose to search for.
    """
    insuring = {"collision": "CLS-COLL-001", "comprehensive": "CLS-COMP-002"}.get(facts["loss_category"])
    candidates = [insuring, "CLS-PER-006", "CLS-DED-004"]
    candidates += [s["clause"] for s in signals] + [g["clause"] for g in gaps]
    clauses = []
    for clause in candidates:
        if clause and clause not in clauses:
            clauses.append(clause)
    return clauses


def code_outcome(signals, gaps):
    """The outcome code would choose on its own (the deterministic fallback): the first outcome in
    PRECEDENCE that is signalled. A documentation gap counts as FLAG (decided 2026-11-04: an
    estimate pending OCR cannot support payment, CLS-DOC-009)."""
    signalled = [s["outcome"] for s in signals]
    if gaps:
        signalled.append("FLAG")
    for outcome in PRECEDENCE:
        if outcome in signalled:
            return outcome
    return "APPROVE"


def note_additions(outcome, signals, gaps):
    """The lines code adds to a note, so nothing the note's own outcome leaves out is lost.

    "Also needs" lists each signal for another outcome (for example a senior adjuster on a FLAG),
    and "Pending documentation" lists each gap. When a FLAG rests on documentation alone, the note
    says code found no fraud indicators, so it is not read as a fraud referral.
    Returns "" when there is nothing to add."""
    lines = []
    others = [s for s in signals if s["outcome"] != outcome]
    if others:
        items = [f"{s['outcome']}: {s['reason']} ({s['clause']})" for s in others]
        lines.append("Also needs: " + "; ".join(items) + ".")
    if gaps:
        items = [f"{g['reason']} ({g['clause']})" for g in gaps]
        lines.append("Pending documentation: " + "; ".join(items) + ".")
        code_found_fraud = any(s["outcome"] == "FLAG" for s in signals)
        if outcome == "FLAG" and not code_found_fraud:
            lines.append("Code found no fraud indicators: this FLAG is for the pending documentation.")
    return " ".join(lines)
