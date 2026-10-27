"""Build the seed CSV files for the ClaimSense database.

    python3 platform/db/seed/build_seed.py

Reads the course fixtures (data/course_fixtures), the users (data/identity/users.json) and the
injected bad chunk (seed/injected_clauses.json), and writes one CSV per table into seed/data/.
load.sh then copies each CSV into Postgres. Standard library only.

The load-time guardrail runs here: every policy clause goes to exactly one of
clause_index.csv (searchable) or clause_quarantine.csv (never loaded for retrieval).
"""
import csv
import json
from pathlib import Path

from guardrail import find_injection

SEED_DIR = Path(__file__).resolve().parent
REPO = SEED_DIR.parents[2]
FIXTURES = REPO / "data" / "course_fixtures"
USERS_FILE = REPO / "data" / "identity" / "users.json"
INJECTED_FILE = SEED_DIR / "injected_clauses.json"
OUT_DIR = SEED_DIR / "data"


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def csv_value(value):
    """Turn a Python value into the text Postgres expects in a CSV file."""
    if value is None:
        return ""            # an empty unquoted field is loaded as NULL
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def write_csv(table, columns, rows):
    """Write rows (a list of dicts) to seed/data/<table>.csv with a header line."""
    path = OUT_DIR / f"{table}.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([csv_value(row[col]) for col in columns])
    print(f"    {table}.csv: {len(rows)} rows")


def build_users():
    users = []
    for u in read_json(USERS_FILE)["users"]:
        users.append({
            "user_id": u["user_id"],
            "full_name": u["name"],
            "user_group": u["group"],
            "status": u["status"],
            "test_only": u["test_only"],
        })
    return users


def build_clauses():
    """The manual's 12 clauses plus the injected chunk, as the client system holds them."""
    clauses = []
    for c in read_json(FIXTURES / "policy_clauses.json"):
        clauses.append({
            "clause_id": c["clause_id"],
            "title": c["title"],
            "text": c["text"],
            "source": c["source"],
            "is_poisoned": False,
        })
    for c in read_json(INJECTED_FILE):
        clauses.append(c)
    return clauses


def split_clauses(clauses):
    """Run the guardrail: clean clauses go to the index, suspicious ones to quarantine."""
    index_rows = []
    quarantine_rows = []
    for c in clauses:
        reason = find_injection(c["title"] + " " + c["text"])
        if reason is None:
            index_rows.append({"clause_id": c["clause_id"], "title": c["title"], "text": c["text"]})
        else:
            quarantine_rows.append({"clause_id": c["clause_id"], "reason": reason})
    return index_rows, quarantine_rows


def main():
    OUT_DIR.mkdir(exist_ok=True)
    print("==> building seed CSVs from the course fixtures")

    users = build_users()
    write_csv("users", ["user_id", "full_name", "user_group", "status", "test_only"], users)

    policies = read_json(FIXTURES / "policies.json")
    for p in policies:
        p["declarations_file"] = "data/course_fixtures/" + p["declarations_file"]
    write_csv("policies", [
        "policy_id", "holder_first", "holder_last", "vehicle_vin", "vehicle_year", "vehicle_make",
        "vehicle_model", "vehicle_acv_usd", "coverage_type", "collision_coverage",
        "comprehensive_coverage", "collision_deductible_usd", "comprehensive_deductible_usd",
        "liability_limit", "medpay_limit_usd", "policy_status", "policy_start", "policy_end",
        "declarations_file"], policies)

    clauses = build_clauses()
    write_csv("policy_clauses", ["clause_id", "title", "text", "source", "is_poisoned"], clauses)

    claims = read_json(FIXTURES / "claims.json")
    write_csv("claims", [
        "claim_id", "policy_id", "vehicle_vin", "vehicle_year", "vehicle_make", "vehicle_model",
        "vehicle_acv_usd", "incident_date", "incident_type", "incident_description",
        "damage_description", "repair_estimate_usd", "injuries_reported", "police_report_filed",
        "assigned_adjuster", "prior_claims_12mo", "fraud_risk_score", "claim_status", "created_at"], claims)

    documents = read_json(FIXTURES / "documents.json")
    for d in documents:
        d["file_path"] = "data/course_fixtures/" + d["file"]
    write_csv("documents", [
        "document_id", "claim_id", "document_type", "description", "upload_date", "page_count",
        "ocr_status", "uploaded_by", "file_path", "ocr_text"], documents)

    index_rows, quarantine_rows = split_clauses(clauses)
    write_csv("clause_index", ["clause_id", "title", "text"], index_rows)
    write_csv("clause_quarantine", ["clause_id", "reason"], quarantine_rows)
    for q in quarantine_rows:
        print(f"    guardrail quarantined {q['clause_id']}: {q['reason']}")


if __name__ == "__main__":
    main()
