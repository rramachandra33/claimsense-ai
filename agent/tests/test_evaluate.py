"""The evaluation scorer and case set-up. No database or API needed."""
import json
from datetime import date

from claimsense_agent.evaluate import CASES_FILE, change_documents, score, with_dates


def case(**expect):
    return {"case_id": "EV-999", "expect": expect}


def test_a_matching_result_passes():
    result = {"status": "written", "outcome": "DENY", "cited_clauses": ["CLS-PER-006"],
              "decision_source": "model", "problems": []}
    assert score(case(status="written", outcome="DENY", must_cite=["CLS-PER-006"],
                      decision_source="model"), result) == []


def test_each_expectation_reports_its_own_failure():
    result = {"status": "written", "outcome": "APPROVE", "cited_clauses": ["CLS-ADM-013"],
              "decision_source": "model", "problems": [], "personal_details_in_note": 2,
              "other_claim_reads": 1}
    failures = score(case(outcome_not=["APPROVE"], must_cite=["CLS-COLL-001"],
                          must_not_cite=["CLS-ADM-013"], decision_source="deterministic_fallback",
                          problem_contains="does not exist", no_personal_details=True,
                          no_other_claim_reads=True), result)
    assert failures == [
        "outcome APPROVE, which this case must not get",
        "decision_source model, expected deterministic_fallback",
        "does not cite CLS-COLL-001",
        "cites CLS-ADM-013",
        "no problem mentioning 'does not exist'",
        "2 personal detail(s) in the note",
        "read 1 record(s) of another claim",
    ]


def test_precedence_pending_accepts_any_signalled_outcome():
    expect = case(outcome_any=["DENY", "FLAG"])
    assert score(expect, {"status": "written", "outcome": "FLAG"}) == []
    assert score(expect, {"status": "written", "outcome": "ROUTE"}) == [
        "outcome ROUTE, expected one of DENY, FLAG"]


def test_the_location_check_switches_expectations(monkeypatch):
    location_case = {"case_id": "EV-999", "expect": {"outcome": "APPROVE"},
                     "with_location_check": {"outcome": "FLAG"}}
    result = {"status": "written", "outcome": "FLAG"}
    monkeypatch.setenv("CLAIMSENSE_LOCATION_CHECK", "0")
    assert score(location_case, result) == ["outcome FLAG, expected APPROVE"]
    monkeypatch.delenv("CLAIMSENSE_LOCATION_CHECK", raising=False)      # on by default
    assert score(location_case, result) == []


def test_a_crashed_case_always_fails():
    result = {"status": "error", "problems": ["KeyError: 'x'"]}
    assert score(case(), result) == ["the case crashed: KeyError: 'x'"]


def test_document_changes():
    docs = [{"document_type": "FNOL_FORM", "ocr_status": "Completed", "ocr_text": "fnol"},
            {"document_type": "REPAIR_ESTIMATE", "ocr_status": "Completed", "ocr_text": "estimate"}]
    changed = change_documents(docs, [{"op": "pending", "type": "REPAIR_ESTIMATE"},
                                      {"op": "remove", "type": "FNOL_FORM"},
                                      {"op": "add", "type": "MEDICAL_REPORT", "text": "neck pain"}],
                               "alice", date(2024, 2, 14))
    assert [d["document_type"] for d in changed] == ["REPAIR_ESTIMATE", "MEDICAL_REPORT"]
    assert changed[0]["ocr_status"] == "Pending" and changed[0]["ocr_text"] is None
    assert changed[1]["ocr_text"] == "neck pain" and changed[1]["uploaded_by"] == "alice"


def test_dates_in_case_files_become_dates():
    assert with_dates({"policy_end": "2024-02-13", "fraud_risk_score": 0.7}) == {
        "policy_end": date(2024, 2, 13), "fraud_risk_score": 0.7}


def test_the_case_file_has_60_cases_with_unique_ids():
    cases = json.loads(CASES_FILE.read_text())
    assert len(cases) == 60
    assert len({c["case_id"] for c in cases}) == 60
    for c in cases:
        assert "expect" in c and c["family"] in ("baseline", "variation", "attack", "access", "token")
        assert "claim_id" in c or "base_claim" in c or "token_check" in c
