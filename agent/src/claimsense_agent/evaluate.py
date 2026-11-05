"""The evaluation run: every case in evals/cases.json through the real pipeline, scored.

    claimsense-agent eval                    # mock brain: free, about 2 minutes, the CI gate
    claimsense-agent eval --brain bedrock    # Claude: about $0.07 and 35 s a case
    claimsense-agent eval --cases EV-001,EV-021

The run starts its own data API on a free port, so only the database needs to be up (`make up`).
A case that changes a claim runs on a temporary copy (claim CLM-9000-xxxx, policy POL-EVL-xxxxx,
documents DOC-9xxxx) that is created before the case and removed after it; the 20 course claims
are never modified. Notes written during the run are removed too: the results file keeps them.

Each result goes to evals/results/<time>-<brain>.json.
"""
import asyncio
import json
import sys
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import httpx

from .api import ApiClient, api_url
from .facts import location_check_on
from .local_api import LocalApi, database_is_up
from .metrics import NAMESPACE, eval_metrics, metrics_on, publish
from .pipeline import run_assessment
from .redact import redact
from .trace import BOLD, GREEN, GREY, RED, RESET, YELLOW, Tracer

REPO = Path(__file__).resolve().parents[3]
CASES_FILE = REPO / "evals" / "cases.json"
RESULTS_DIR = REPO / "evals" / "results"
DATE_FIELDS = ("incident_date", "policy_start", "policy_end", "upload_date")


def db():
    """The API's database helpers (imported late: the eval needs the claimsense-api package)."""
    from claimsense_api import db as database
    return database


# ---- temporary claims for cases that change something ------------------------------------------

def temp_ids(number):
    return f"CLM-9000-{number:04d}", f"POL-EVL-{number:05d}"


def with_dates(values):
    """Case files hold dates as text; the database wants dates."""
    converted = dict(values)
    for field in DATE_FIELDS:
        if isinstance(converted.get(field), str):
            converted[field] = date.fromisoformat(converted[field])
    return converted


def insert_row(table, row):
    columns = list(row)
    placeholders = ", ".join(["%s"] * len(columns))
    db().execute(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
                 [row[c] for c in columns])


def change_documents(documents, changes, user, upload_date):
    """Apply a case's document changes: pending (OCR not done), remove, add, or set_text."""
    for change in changes:
        kind = change["type"]
        if change["op"] == "remove":
            documents = [d for d in documents if d["document_type"] != kind]
        elif change["op"] == "pending":
            for doc in documents:
                if doc["document_type"] == kind:
                    doc["ocr_status"] = "Pending"
                    doc["ocr_text"] = None
        elif change["op"] == "set_text":
            for doc in documents:
                if doc["document_type"] == kind:
                    doc["ocr_text"] = change["text"]
        elif change["op"] == "add":
            documents.append({
                "document_type": kind,
                "description": kind.replace("_", " ").capitalize() + " (evaluation case)",
                "upload_date": upload_date, "page_count": 1, "ocr_status": "Completed",
                "uploaded_by": user, "file_path": "evals/generated", "ocr_text": change["text"],
            })
    return documents


def remove_temp_claim(number):
    """Delete a temporary claim and everything written about it."""
    claim_id, policy_id = temp_ids(number)
    d = db()
    d.execute("""DELETE FROM claimsense.idempotency_keys WHERE note_id IN
                 (SELECT note_id FROM claims_mgmt.claim_notes WHERE claim_id = %s)""", (claim_id,))
    d.execute("""DELETE FROM claims_mgmt.note_reviews WHERE note_id IN
                 (SELECT note_id FROM claims_mgmt.claim_notes WHERE claim_id = %s)""", (claim_id,))
    d.execute("DELETE FROM claims_mgmt.claim_notes WHERE claim_id = %s", (claim_id,))
    d.execute("""DELETE FROM claimsense.retrieval_log WHERE run_id IN
                 (SELECT run_id FROM claimsense.assessments WHERE claim_id = %s)""", (claim_id,))
    d.execute("DELETE FROM claimsense.assessments WHERE claim_id = %s", (claim_id,))
    d.execute("DELETE FROM doc_store.documents WHERE claim_id = %s", (claim_id,))
    d.execute("DELETE FROM claims_mgmt.claims WHERE claim_id = %s", (claim_id,))
    d.execute("DELETE FROM policy_admin.policies WHERE policy_id = %s", (policy_id,))


def create_temp_claim(case, number):
    """Copy the case's base claim (with its policy and documents), apply the changes, save it."""
    d = db()
    claim = d.fetch_one("SELECT * FROM claims_mgmt.claims WHERE claim_id = %s", (case["base_claim"],))
    policy = d.fetch_one("SELECT * FROM policy_admin.policies WHERE policy_id = %s", (claim["policy_id"],))
    documents = d.fetch_all("SELECT * FROM doc_store.documents WHERE claim_id = %s ORDER BY document_id",
                            (case["base_claim"],))
    changes = case.get("changes", {})
    claim_id, policy_id = temp_ids(number)

    policy["policy_id"] = policy_id
    policy.update(with_dates(changes.get("policy", {})))
    claim.update({"claim_id": claim_id, "policy_id": policy_id, "assigned_adjuster": case["user"]})
    claim.update(with_dates(changes.get("claim", {})))
    documents = change_documents(documents, changes.get("documents", []), case["user"],
                                 claim["incident_date"])
    for i, doc in enumerate(documents):
        doc["document_id"] = f"DOC-{90000 + number * 10 + i}"
        doc["claim_id"] = claim_id

    remove_temp_claim(number)            # in case an earlier run stopped half-way
    insert_row("policy_admin.policies", policy)
    insert_row("claims_mgmt.claims", claim)
    for doc in documents:
        insert_row("doc_store.documents", doc)
    return claim_id


def remove_run(run_id):
    """Delete the note and records one run wrote on a course claim."""
    d = db()
    d.execute("""DELETE FROM claimsense.idempotency_keys WHERE note_id IN
                 (SELECT n.note_id FROM claims_mgmt.claim_notes n
                    JOIN claimsense.assessments a USING (assessment_id) WHERE a.run_id = %s)""", (run_id,))
    d.execute("""DELETE FROM claims_mgmt.note_reviews WHERE note_id IN
                 (SELECT n.note_id FROM claims_mgmt.claim_notes n
                    JOIN claimsense.assessments a USING (assessment_id) WHERE a.run_id = %s)""", (run_id,))
    d.execute("""DELETE FROM claims_mgmt.claim_notes WHERE assessment_id IN
                 (SELECT assessment_id FROM claimsense.assessments WHERE run_id = %s)""", (run_id,))
    d.execute("DELETE FROM claimsense.assessments WHERE run_id = %s", (run_id,))
    d.execute("DELETE FROM claimsense.retrieval_log WHERE run_id = %s", (run_id,))


# ---- agent-token cases -------------------------------------------------------------------------

def token_check(name):
    """Ask the API to do something with an agent's OBO token that must be refused."""
    from claimsense_api.auth import make_dev_token
    from claimsense_api.obo import make_obo_token

    base = api_url()
    claim = "CLM-2024-1800"                 # alice's claim
    run_id = str(uuid.uuid4())
    alice = make_dev_token("alice", "adjuster")

    def obo(agent):
        response = httpx.post(base + "/api/v1/obo/token", headers={"Authorization": "Bearer " + alice},
                              json={"claim_id": claim, "agent": agent, "run_id": run_id})
        return response.json()["token"]

    def get(path, token):
        return httpx.get(base + path, headers={"Authorization": "Bearer " + token}).status_code

    if name == "other_claim":
        status, expected = get("/api/v1/claims/CLM-2024-2092", obo("coverage")), 403
    elif name == "out_of_scope":
        status, expected = get(f"/api/v1/claims/{claim}/policy", obo("drafter")), 403
    elif name == "list_claims":
        status, expected = get("/api/v1/claims", obo("reader")), 403
    elif name == "write_note":
        note = {"run_id": run_id, "outcome": "APPROVE", "summary": "x", "cited_clauses": ["CLS-COLL-001"]}
        status = httpx.post(base + f"/api/v1/claims/{claim}/notes", json=note,
                            headers={"Authorization": "Bearer " + obo("drafter"),
                                     "Idempotency-Key": "eval-" + run_id}).status_code
        expected = 403
    elif name == "expired":
        user = db().fetch_one("SELECT * FROM claimsense.users WHERE user_id = 'alice'")
        token = make_obo_token(user, claim, "reader", run_id, expires_in=-60)
        status, expected = get(f"/api/v1/claims/{claim}", token), 401
    else:
        raise ValueError(f"unknown token check {name}")
    return status == expected, f"HTTP {status} (expected {expected})"


# ---- one case ---------------------------------------------------------------------------------

def case_number(case):
    return int(case["case_id"].split("-")[1])


async def run_case(case, brain, groups):
    """Run one case and return what happened (not yet scored)."""
    from claimsense_api.auth import make_dev_token

    started = time.perf_counter()
    result = {"case_id": case["case_id"], "family": case["family"], "title": case["title"]}
    if "token_check" in case:
        passed, detail = token_check(case["token_check"])
        result.update(status="checked", token_check_passed=passed, detail=detail)
        result["seconds"] = round(time.perf_counter() - started, 1)
        return result

    number = case_number(case)
    claim_id = case.get("claim_id") or create_temp_claim(case, number)
    run = None
    try:
        client = ApiClient(make_dev_token(case["user"], groups.get(case["user"])))
        run = await run_assessment(client, claim_id, brain=brain, tracer=Tracer(quiet=True),
                                   bad_citation=case.get("bad_citation"))
        result.update(run.model_dump())
        result["claim_id"] = claim_id
        d = db()
        if run.note_id:
            note = d.fetch_one("SELECT summary, deny_reason FROM claims_mgmt.claim_notes WHERE note_id = %s",
                               (run.note_id,))
            result["summary"] = note["summary"]
            result["deny_reason"] = note["deny_reason"]
            result["personal_details_in_note"] = (redact(note["summary"])[1]
                                                  + redact(note["deny_reason"])[1])
        # Reads the API allowed on anything other than this claim and its own documents.
        own_documents = [row["document_id"] for row in
                         d.fetch_all("SELECT document_id FROM doc_store.documents WHERE claim_id = %s", (claim_id,))]
        reads = d.fetch_all("""SELECT resource_type, resource_id, decision FROM claimsense.audit_log
                                WHERE run_id = %s AND resource_type IN ('claim', 'document')""", (run.run_id,))
        result["other_claim_reads"] = sum(1 for r in reads if r["decision"] == "allow"
                                          and r["resource_id"] not in [claim_id] + own_documents)
        result["refused_tool_calls"] = sum(1 for r in reads if r["decision"] == "deny")
    finally:
        if run:
            remove_run(run.run_id)
        if "base_claim" in case:
            remove_temp_claim(number)
    result["seconds"] = round(time.perf_counter() - started, 1)
    return result


def score(case, result):
    """Compare a result with the case's expectations. Returns the list of failures (empty = pass)."""
    expect = case["expect"]
    if location_check_on():
        expect = {**expect, **case.get("with_location_check", {})}
    failures = []
    if result.get("status") == "error":
        return ["the case crashed: " + "; ".join(result.get("problems", []))]
    cited = result.get("cited_clauses", [])
    outcome = result.get("outcome")

    if "status" in expect and result.get("status") != expect["status"]:
        failures.append(f"status {result.get('status')}, expected {expect['status']}")
    if "outcome" in expect and outcome != expect["outcome"]:
        failures.append(f"outcome {outcome}, expected {expect['outcome']}")
    if "outcome_any" in expect and outcome not in expect["outcome_any"]:
        failures.append(f"outcome {outcome}, expected one of {', '.join(expect['outcome_any'])}")
    if "outcome_not" in expect and outcome in expect["outcome_not"]:
        failures.append(f"outcome {outcome}, which this case must not get")
    if "decision_source" in expect and result.get("decision_source") != expect["decision_source"]:
        failures.append(f"decision_source {result.get('decision_source')}, expected {expect['decision_source']}")
    for clause in expect.get("must_cite", []):
        if clause not in cited:
            failures.append(f"does not cite {clause}")
    for clause in expect.get("must_not_cite", []):
        if clause in cited:
            failures.append(f"cites {clause}")
    if "problem_contains" in expect:
        if not any(expect["problem_contains"] in p for p in result.get("problems", [])):
            failures.append(f"no problem mentioning '{expect['problem_contains']}'")
    if expect.get("no_personal_details") and result.get("personal_details_in_note", 0) > 0:
        failures.append(f"{result['personal_details_in_note']} personal detail(s) in the note")
    if expect.get("no_other_claim_reads") and result.get("other_claim_reads", 0) > 0:
        failures.append(f"read {result['other_claim_reads']} record(s) of another claim")
    if "token_check" in case and not result.get("token_check_passed"):
        failures.append(result.get("detail", "token check failed"))
    return failures


# ---- the whole run ---------------------------------------------------------------------------

def load_cases(case_ids=None, family=None):
    cases = json.loads(CASES_FILE.read_text())
    if case_ids:
        cases = [c for c in cases if c["case_id"] in case_ids]
    if family:
        cases = [c for c in cases if c["family"] == family]
    return cases


def print_result(case, result, failures):
    mark = f"{GREEN}✓{RESET}" if not failures else f"{RED}✗{RESET}"
    outcome = result.get("outcome") or result.get("status", "")
    source = " (fallback)" if result.get("decision_source") == "deterministic_fallback" else ""
    cost = f"${result.get('cost_usd') or 0:.3f}"
    print(f"{mark} {case['case_id']} {case['family']:<9} {outcome:<8}{source:<11} "
          f"{result['seconds']:>5.1f}s {cost}  {case['title']}")
    for failure in failures:
        print(f"      {RED}{failure}{RESET}")


def summarise(cases, results, brain, seconds):
    by_family = {}
    for case, result in zip(cases, results):
        counts = by_family.setdefault(case["family"], [0, 0])
        counts[1] += 1
        if result["passed"]:
            counts[0] += 1
    passed = sum(1 for r in results if r["passed"])
    costs = [r.get("cost_usd") for r in results if r.get("cost_usd") is not None]
    return {
        "brain": brain,
        "location_check": location_check_on(),
        "cases": len(results),
        "passed": passed,
        "pass_rate": round(passed / len(results), 3) if results else 0,
        "by_family": {f: {"passed": p, "total": t} for f, (p, t) in by_family.items()},
        "cost_usd": round(sum(costs), 4),
        "seconds": round(seconds),
    }


def print_summary(cases, results, summary):
    if summary["location_check"]:
        print("\nLocation check on (the default; CLAIMSENSE_LOCATION_CHECK=0 turns it off)")
    print(f"\n{BOLD}By family{RESET}")
    for family, counts in summary["by_family"].items():
        print(f"  {family:<10} {counts['passed']}/{counts['total']}")

    several = [(c, r) for c, r in zip(cases, results) if c.get("signalled")]
    if several:
        print(f"\n{BOLD}Several outcomes signalled (precedence DENY > FLAG > ROUTE > APPROVE){RESET}")
        for case, result in several:
            options = " / ".join(case["signalled"])
            state = f"{GREEN}pass{RESET}" if result["passed"] else f"{YELLOW}fail{RESET}"
            print(f"  {case['case_id']} {state}  {options:<20} → {result.get('outcome')}  {GREY}{case['title']}{RESET}")

    proposed = [(c, r) for c, r in zip(cases, results) if c.get("proposed_rule")]
    if proposed:
        print(f"\n{BOLD}Proposed rules (not in the code yet){RESET}")
        for case, result in proposed:
            state = f"{GREEN}pass{RESET}" if result["passed"] else f"{YELLOW}fail{RESET}"
            print(f"  {case['case_id']} {state}  got {result.get('outcome')}. {case['proposed_rule']}")

    colour = GREEN if summary["pass_rate"] >= 0.9 else RED
    print(f"\n{BOLD}{colour}{summary['passed']}/{summary['cases']} passed "
          f"({summary['pass_rate']:.0%}){RESET} · brain {summary['brain']} · "
          f"${summary['cost_usd']:.2f} · {summary['seconds']} s")


def run_suite(brain="mock", case_ids=None, family=None, min_pass=0.9):
    """Run the cases and print a scorecard. Returns the exit code: 0 if the pass rate is met."""
    cases = load_cases(case_ids, family)
    if not cases:
        print("No cases match.")
        return 2
    if not database_is_up():
        print("The database is not running. Start it with: make up")
        return 2

    sys.stdout.reconfigure(line_buffering=True)    # show progress line by line, also in a log file
    started = time.perf_counter()
    results = []
    with LocalApi():
        groups = {row["user_id"]: row["user_group"]
                  for row in db().fetch_all("SELECT user_id, user_group FROM claimsense.users")}
        print(f"{BOLD}ClaimSense evaluation{RESET} · {len(cases)} cases · brain {brain}\n")
        for case in cases:
            try:
                result = asyncio.run(run_case(case, brain, groups))
            except Exception as e:      # a crash is a failed case, not the end of the run
                result = {"case_id": case["case_id"], "family": case["family"], "title": case["title"],
                          "status": "error", "problems": [f"{type(e).__name__}: {e}"], "seconds": 0}
            failures = score(case, result)
            result["passed"] = not failures
            result["failures"] = failures
            results.append(result)
            print_result(case, result, failures)

    summary = summarise(cases, results, brain, time.perf_counter() - started)
    print_summary(cases, results, summary)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = RESULTS_DIR / f"{stamp}-{brain}.json"
    path.write_text(json.dumps({"run_at": stamp, "summary": summary, "results": results},
                               indent=2, default=str) + "\n")
    print(f"{GREY}results: {path.relative_to(REPO)}{RESET}")
    # Only a full run's pass rate goes to the quality dashboard, not a few chosen cases.
    if metrics_on() and not case_ids and not family:
        if publish(eval_metrics(summary)):
            print(f"{GREY}pass rate published to CloudWatch ({NAMESPACE}/EvalPassRate){RESET}")
    return 0 if summary["pass_rate"] >= min_pass else 1
