#!/usr/bin/env python3
"""Convert the course-supplied fixtures into typed records, the clause corpus and code facts.

    python3 scripts/import_course_fixtures.py

Reads   data/course_fixtures/source/   (copied unchanged from the Week 14 session pack)
Writes  data/course_fixtures/{claims,policies,documents,policy_clauses,facts}.json
        data/course_fixtures/IMPORT_REPORT.md

Needs `pdftotext` (poppler) to read the PDFs. Output is deterministic: records are sorted by id
and no timestamps are written, so re-running gives identical files.

Conversion rules follow the fixtures' own sources:
  - Yes/No -> bool, "N/A" -> null, money and counts -> numbers.
  - A document's text is kept only when its ocr_status is Completed; a Pending document's text is
    null even though the PDF has text, because CLS-DOC-009 says pending documents cannot support
    payment.
  - Facts use only rules stated in the AutoSure Policy Manual (cited per fact). No outcome is
    computed here: decision codes and gate order are still an open question (Q2).
"""
from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "data" / "course_fixtures"
SRC = BASE / "source"
TABLES = SRC / "data"
DOCS = SRC / "synthetic_documents"
MANUAL = DOCS / "AutoSure_Policy_Manual_CLS-001-012.pdf"

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
TOTAL_LOSS_RATIO = Decimal("0.75")        # CLS-TL-005
SENIOR_CONFIRMATION_ABOVE = Decimal("25000")  # CLS-PAY-012
STAMP_LINE = re.compile(r"^(C ?EIVED|RE · RE|AUTOSU|-\d{2}|\d{4}-\d{2})$")
FOOTER_LINE = re.compile(r"^SYNTHETIC DOCUMENT ·")


def rows(name):
    with (TABLES / name).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def yes_no(v):
    if v not in ("Yes", "No"):
        raise ValueError(f"expected Yes/No, got {v!r}")
    return v == "Yes"


def num(v):
    if v in ("N/A", ""):
        return None
    d = Decimal(v)
    return int(d) if d == d.to_integral_value() else float(d)


def pdf_text(path: Path) -> str:
    out = subprocess.run(["pdftotext", "-layout", str(path), "-"], check=True,
                         capture_output=True, text=True).stdout
    lines = []
    for raw in out.splitlines():
        line = re.sub(r" {3,}", "  ", raw.rstrip()).strip()
        if not line or STAMP_LINE.match(line) or FOOTER_LINE.match(line):
            continue
        lines.append(line)
    return "\n".join(lines)


def convert_claim(r):
    return {
        "claim_id": r["claim_id"], "policy_id": r["policy_id"], "vehicle_vin": r["vehicle_vin"],
        "vehicle_year": int(r["vehicle_year"]), "vehicle_make": r["vehicle_make"],
        "vehicle_model": r["vehicle_model"], "vehicle_acv_usd": num(r["vehicle_acv_usd"]),
        "incident_date": r["incident_date"], "incident_type": r["incident_type"],
        "incident_description": r["incident_description"], "damage_description": r["damage_description"],
        "repair_estimate_usd": num(r["repair_estimate_usd"]),
        "injuries_reported": yes_no(r["injuries_reported"]),
        "police_report_filed": yes_no(r["police_report_filed"]),
        "assigned_adjuster": r["assigned_adjuster"], "prior_claims_12mo": int(r["prior_claims_12mo"]),
        "fraud_risk_score": float(r["fraud_risk_score"]), "claim_status": r["claim_status"],
        "created_at": r["created_at"],
    }


def convert_policy(r):
    return {
        "policy_id": r["policy_id"],
        "holder_first": r["holder_first"], "holder_last": r["holder_last"],  # PII: never leaves the mock system
        "vehicle_vin": r["vehicle_vin"], "vehicle_year": int(r["vehicle_year"]),
        "vehicle_make": r["vehicle_make"], "vehicle_model": r["vehicle_model"],
        "vehicle_acv_usd": num(r["vehicle_acv_usd"]), "coverage_type": r["coverage_type"],
        "collision_coverage": yes_no(r["collision_coverage"]),
        "comprehensive_coverage": yes_no(r["comprehensive_coverage"]),
        "collision_deductible_usd": num(r["collision_deductible_usd"]),
        "comprehensive_deductible_usd": num(r["comprehensive_deductible_usd"]),
        "liability_limit": r["liability_limit"], "medpay_limit_usd": num(r["medpay_limit_usd"]),
        "policy_status": r["policy_status"], "policy_start": r["policy_start"], "policy_end": r["policy_end"],
        "declarations_file": f"source/synthetic_documents/policies/{r['policy_id']}_DECLARATIONS.pdf",
    }


def parse_manual():
    text = subprocess.run(["pdftotext", str(MANUAL), "-"], check=True, capture_output=True, text=True).stdout
    text = "\n".join(l for l in text.splitlines()
                     if l.strip() and not FOOTER_LINE.match(l.strip())
                     and not l.startswith("AutoSure Insurance · Underwriting"))
    heads = list(re.finditer(r"^(CLS-[A-Z]+-\d{3}) · (.+)$", text, flags=re.M))
    clauses = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        body = " ".join(text[m.end():end].split())
        clauses.append({"clause_id": m.group(1), "title": m.group(2).strip(), "text": body,
                        "source": "AutoSure_Policy_Manual_CLS-001-012.pdf (v2024.1)"})
    return clauses


def facts_for(c, p, docs):
    dec = lambda v: Decimal(str(v)) if v is not None else None
    estimate, acv = dec(c["repair_estimate_usd"]), dec(c["vehicle_acv_usd"])
    loss_date = date.fromisoformat(c["incident_date"])
    start, end = date.fromisoformat(p["policy_start"]), date.fromisoformat(p["policy_end"])
    in_force = start <= loss_date <= end                                      # CLS-PER-006, inclusive
    category = LOSS_CATEGORY.get(c["incident_type"])
    if p["coverage_type"] == "Liability Only":                                # CLS-LIAB-003
        coverage_purchased = False
    elif category == "collision":
        coverage_purchased = p["collision_coverage"]
    elif category == "comprehensive":
        coverage_purchased = p["comprehensive_coverage"]
    else:
        coverage_purchased = None
    deductible = {"collision": p["collision_deductible_usd"],
                  "comprehensive": p["comprehensive_deductible_usd"]}.get(category)  # CLS-DED-004
    net = None
    if coverage_purchased and deductible is not None and estimate is not None:
        net = max(min(estimate, acv) - dec(deductible), Decimal(0))          # CLS-COLL-001 / CLS-DED-004
    ratio = (estimate / acv).quantize(Decimal("0.0001")) if estimate is not None else None
    by_type = {}
    for d in docs:
        by_type.setdefault(d["document_type"], []).append(d)
    estimates = by_type.get("REPAIR_ESTIMATE", [])
    return {
        "claim_id": c["claim_id"],
        "loss_category": category,
        "in_force_at_loss": in_force,
        "days_after_policy_end": max((loss_date - end).days, 0),
        "status_field_conflict": p["policy_status"] == "Active" and not in_force,
        # Claims management and policy administration each keep their own vehicle record. Money uses
        # the claim's ACV ("immediately before the loss", CLS-COLL-001); a mismatch is evidence, not an error.
        "vin_matches_policy": c["vehicle_vin"] == p["vehicle_vin"],
        "vehicle_matches_policy": all(c[k] == p[k] for k in ("vehicle_year", "vehicle_make", "vehicle_model")),
        "acv_differs_from_policy_usd": num(str(acv - dec(p["vehicle_acv_usd"]))),
        "coverage_purchased_for_loss": coverage_purchased,
        "deductible_usd": num(str(deductible)) if deductible is not None else None,
        "repair_to_acv_ratio": float(ratio) if ratio is not None else None,
        "total_loss_candidate": bool(ratio is not None and ratio >= TOTAL_LOSS_RATIO),  # CLS-TL-005
        "net_payable_if_covered_usd": num(str(net)) if net is not None else None,
        "senior_confirmation_required": bool(net is not None and net > SENIOR_CONFIRMATION_ABOVE),  # CLS-PAY-012
        "documents": {
            "count": len(docs),
            "fnol_count": len(by_type.get("FNOL_FORM", [])),
            "repair_estimate_on_file": bool(estimates),
            "repair_estimate_readable": any(d["ocr_status"] == "Completed" for d in estimates),  # CLS-DOC-009
            "pending_ocr": sorted(d["document_id"] for d in docs if d["ocr_status"] != "Completed"),
            "police_report_on_file": "POLICE_REPORT" in by_type,
            "medical_report_on_no_injury_claim": "MEDICAL_REPORT" in by_type and not c["injuries_reported"],  # CLS-INJ-008
        },
        "rule_sources": ["CLS-PER-006", "CLS-LIAB-003", "CLS-COMP-002", "CLS-DED-004", "CLS-COLL-001",
                         "CLS-TL-005", "CLS-PAY-012", "CLS-DOC-009", "CLS-INJ-008"],
    }


def outcome_signals(c, f):
    """Which of the four outcomes each signal points to. Precedence between them is deliberately
    NOT decided here (open question 2, deferred): these claims are the test cases for that decision."""
    s = []
    if not f["in_force_at_loss"]:
        s.append(("DENY", f"loss {f['days_after_policy_end']} days after policy end (CLS-PER-006)"))
    if f["coverage_purchased_for_loss"] is False:
        s.append(("DENY", f"no {f['loss_category']} cover on this policy (CLS-LIAB-003)"))
    if f["total_loss_candidate"]:
        s.append(("ROUTE", f"repair/ACV {f['repair_to_acv_ratio']} ≥ 0.75, total-loss appraiser (CLS-TL-005)"))
    if c["injuries_reported"]:
        s.append(("ROUTE", "injury reported, injury-qualified adjuster (CLS-INJ-008)"))
    if f["senior_confirmation_required"]:
        s.append(("ROUTE", f"net payable {f['net_payable_if_covered_usd']} > 25000, senior adjuster (CLS-PAY-012)"))
    fraud = []
    if c["prior_claims_12mo"] >= 2:
        fraud.append(f"{c['prior_claims_12mo']} prior claims in 12 months")
    if not c["police_report_filed"] and (c["injuries_reported"] or "airbag" in c["damage_description"].lower()):
        fraud.append("no police report with injury or airbag deployment")
    if c["fraud_risk_score"] >= 0.70:
        fraud.append(f"vendor score {c['fraud_risk_score']} (0.70 is a provisional threshold)")
    if fraud:
        s.append(("FLAG", "fraud indicators: " + "; ".join(fraud) + " (CLS-FRD-007)"))
    # Documentation gaps are reported separately: whether they mean FLAG or ROUTE is part of the
    # deferred precedence decision, so they don't count towards a conflict.
    d, docs = f["documents"], []
    if not d["repair_estimate_readable"]:
        docs.append("no readable repair estimate" + (" (pending OCR)" if d["repair_estimate_on_file"] else " (none on file)")
                    + " (CLS-DOC-009)")
    if d["medical_report_on_no_injury_claim"]:
        docs.append("medical report on a no-injury FNOL (CLS-INJ-008)")
    return s, docs


def check_invariants(claims, policies, documents):
    pol = {p["policy_id"]: p for p in policies}
    clm = {c["claim_id"]: c for c in claims}
    out = []

    def inv(code, text, bad):
        out.append((code, text, bad))

    inv("I-1", "every claim's policy exists", [c["claim_id"] for c in claims if c["policy_id"] not in pol])
    inv("I-2", "claim VIN equals policy VIN",
        [c["claim_id"] for c in claims if c["policy_id"] in pol and c["vehicle_vin"] != pol[c["policy_id"]]["vehicle_vin"]])
    inv("I-3", "claim ACV equals policy ACV",
        [c["claim_id"] for c in claims if c["policy_id"] in pol and c["vehicle_acv_usd"] != pol[c["policy_id"]]["vehicle_acv_usd"]])
    inv("I-4", "every document's claim exists", [d["document_id"] for d in documents if d["claim_id"] not in clm])
    inv("I-5", "no document uploaded before the incident",
        [d["document_id"] for d in documents if d["claim_id"] in clm and d["upload_date"] < clm[d["claim_id"]]["incident_date"]])
    inv("I-6", "Liability Only has no physical-damage cover or deductibles",
        [p["policy_id"] for p in policies if p["coverage_type"] == "Liability Only" and
         (p["collision_coverage"] or p["comprehensive_coverage"] or
          p["collision_deductible_usd"] is not None or p["comprehensive_deductible_usd"] is not None)])
    inv("I-7", "policy start before end", [p["policy_id"] for p in policies if p["policy_start"] >= p["policy_end"]])
    fnols = {}
    for d in documents:
        if d["document_type"] == "FNOL_FORM":
            fnols[d["claim_id"]] = fnols.get(d["claim_id"], 0) + 1
    inv("I-8", "every claim has exactly one FNOL", [c["claim_id"] for c in claims if fnols.get(c["claim_id"], 0) != 1])
    inv("I-9", "every incident type maps to a loss category",
        [c["claim_id"] for c in claims if c["incident_type"] not in LOSS_CATEGORY])
    inv("PDF", "every document has its PDF", [d["document_id"] for d in documents if not (BASE / d["file"]).exists()])
    return out


def main():
    if shutil.which("pdftotext") is None:
        raise SystemExit("pdftotext not found: install poppler (brew install poppler)")

    claims = sorted((convert_claim(r) for r in rows("claimsense_claims.csv")), key=lambda c: c["claim_id"])
    policies = sorted((convert_policy(r) for r in rows("claimsense_policies.csv")), key=lambda p: p["policy_id"])
    index = {r["document_id"]: r for r in csv.DictReader((DOCS / "index.csv").open(newline="", encoding="utf-8"))}
    documents = []
    for r in rows("claimsense_documents.csv"):
        file = f"source/synthetic_documents/{index[r['document_id']]['file']}"
        documents.append({
            "document_id": r["document_id"], "claim_id": r["claim_id"], "document_type": r["document_type"],
            "description": r["description"], "upload_date": r["upload_date"],
            "page_count": int(r["page_count"]), "ocr_status": r["ocr_status"], "uploaded_by": r["uploaded_by"],
            "file": file,
            "ocr_text": pdf_text(BASE / file) if r["ocr_status"] == "Completed" else None,  # CLS-DOC-009
        })
    documents.sort(key=lambda d: d["document_id"])
    clauses = parse_manual()

    pol = {p["policy_id"]: p for p in policies}
    docs_by_claim = {}
    for d in documents:
        docs_by_claim.setdefault(d["claim_id"], []).append(d)
    facts = [facts_for(c, pol[c["policy_id"]], docs_by_claim.get(c["claim_id"], [])) for c in claims]
    invariants = check_invariants(claims, policies, documents)

    def dump(name, obj):
        (BASE / name).write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    dump("claims.json", claims)
    dump("policies.json", policies)
    dump("documents.json", documents)
    dump("policy_clauses.json", clauses)
    dump("facts.json", facts)

    lines = ["# Course fixture import report", "",
             "Generated by `scripts/import_course_fixtures.py` from `data/course_fixtures/source/`.", "",
             f"- Claims: {len(claims)} · policies: {len(policies)} · documents: {len(documents)} "
             f"({sum(d['ocr_text'] is not None for d in documents)} with text, "
             f"{sum(d['ocr_text'] is None for d in documents)} pending OCR) · clauses: {len(clauses)}",
             f"- Adjusters in the data: {', '.join(sorted({c['assigned_adjuster'] for c in claims}))}", "",
             "## Invariants", "", "| ID | Rule | Result |", "|---|---|---|"]
    for code, text, bad in invariants:
        lines.append(f"| {code} | {text} | {'pass' if not bad else 'FAIL: ' + ', '.join(bad)} |")
    lines += ["", "## Code facts per claim", "",
              "| Claim | Category | In force | Days late | Status conflict | Covered | Deductible | Ratio | TL | Net payable | Senior | Pending OCR | Med. on no-injury |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for f in facts:
        d = f["documents"]
        lines.append(" | ".join([
            f"| {f['claim_id']}", str(f["loss_category"]), str(f["in_force_at_loss"]), str(f["days_after_policy_end"]),
            str(f["status_field_conflict"]), str(f["coverage_purchased_for_loss"]), str(f["deductible_usd"]),
            str(f["repair_to_acv_ratio"]), str(f["total_loss_candidate"]), str(f["net_payable_if_covered_usd"]),
            str(f["senior_confirmation_required"]), ", ".join(d["pending_ocr"]) or "-",
            str(d["medical_report_on_no_injury_claim"]) + " |"]))
    clm = {c["claim_id"]: c for c in claims}
    conflicts = []
    for f in facts:
        sig, doc_gaps = outcome_signals(clm[f["claim_id"]], f)
        if len({o for o, _ in sig}) > 1:
            conflicts.append({"claim_id": f["claim_id"],
                              "outcomes_signalled": sorted({o for o, _ in sig}),
                              "signals": [{"outcome": o, "reason": r} for o, r in sig],
                              "documentation_gaps": doc_gaps,
                              "expected_outcome": None,
                              "note": "Precedence deferred (open question 2). Fill expected_outcome once decided."})
    (ROOT / "evals").mkdir(exist_ok=True)
    (ROOT / "evals" / "precedence_cases.json").write_text(json.dumps(conflicts, indent=2, ensure_ascii=False) + "\n",
                                                          encoding="utf-8")
    lines += ["", "## Claims where more than one outcome is signalled (precedence test cases)", "",
              "Written to `evals/precedence_cases.json`. Precedence is deferred (open question 2).", "",
              "| Claim | Outcomes signalled | Signals | Documentation gaps |", "|---|---|---|---|"]
    for k in conflicts:
        lines.append(f"| {k['claim_id']} | {' + '.join(k['outcomes_signalled'])} | "
                     + "; ".join(f"{s['outcome']}: {s['reason']}" for s in k["signals"]) + " | "
                     + ("; ".join(k["documentation_gaps"]) or "-") + " |")
    (BASE / "IMPORT_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    failed = [code for code, _, bad in invariants if bad]
    print(f"claims={len(claims)} policies={len(policies)} documents={len(documents)} clauses={len(clauses)} "
          f"invariant failures={failed or 'none'}")


if __name__ == "__main__":
    main()
