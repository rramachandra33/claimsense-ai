"""Code facts and the draft checks. No database or API needed.

    cd agent && uv run --extra dev pytest -q tests/test_facts.py
"""
import json
from pathlib import Path

import httpx
import pytest

from claimsense_agent import api
from claimsense_agent.facts import code_outcome, compute_facts, documentation_gaps, outcome_signals
from claimsense_agent.pipeline import check_draft, fallback_draft
from claimsense_agent.schemas import DraftOutput

FIXTURES = Path(__file__).resolve().parents[2] / "data" / "course_fixtures"
EVALS = Path(__file__).resolve().parents[2] / "evals"


def load(name):
    return json.loads((FIXTURES / name).read_text())


def course_claims():
    """(claim, policy, documents) for each of the 20 course claims."""
    policies = {p["policy_id"]: p for p in load("policies.json")}
    documents = load("documents.json")
    for claim in load("claims.json"):
        docs = [d for d in documents if d["claim_id"] == claim["claim_id"]]
        yield claim, policies[claim["policy_id"]], docs


def test_facts_match_the_import_script_for_all_20_claims():
    expected = {f["claim_id"]: f for f in load("facts.json")}
    count = 0
    for claim, policy, docs in course_claims():
        assert compute_facts(claim, policy, docs) == expected[claim["claim_id"]]
        count += 1
    assert count == 20


def test_signals_match_the_precedence_cases():
    cases = {c["claim_id"]: c for c in json.loads((EVALS / "precedence_cases.json").read_text())}
    for claim, policy, docs in course_claims():
        if claim["claim_id"] in cases:
            signals = outcome_signals(claim, compute_facts(claim, policy, docs))
            outcomes = sorted({s["outcome"] for s in signals})
            assert outcomes == sorted(cases[claim["claim_id"]]["outcomes_signalled"])


def test_lapsed_policy_is_a_deny_signal():
    claim, policy, docs = next(c for c in course_claims() if c[0]["claim_id"] == "CLM-2024-2822")
    signals = outcome_signals(claim, compute_facts(claim, policy, docs))
    assert {"outcome": "DENY", "clause": "CLS-PER-006", "reason": "loss 3 days after policy end"} in signals


def test_code_outcome_approves_only_when_nothing_was_found():
    assert code_outcome([], []) == "APPROVE"
    assert code_outcome([], [{"clause": "CLS-DOC-009", "reason": "x"}]) == "FLAG"
    assert code_outcome([{"outcome": "ROUTE", "clause": "CLS-TL-005", "reason": "x"},
                         {"outcome": "DENY", "clause": "CLS-PER-006", "reason": "y"}], []) == "DENY"


# --- the draft checks -------------------------------------------------------------

ROUTE_SIGNAL = [{"outcome": "ROUTE", "clause": "CLS-TL-005", "reason": "total-loss candidate"}]


def draft(outcome, cited, deny_reason=None):
    return DraftOutput(outcome=outcome, summary="s", cited_clauses=cited, deny_reason=deny_reason)


def test_a_clean_draft_passes():
    assert check_draft(draft("ROUTE", ["CLS-TL-005"]), ROUTE_SIGNAL, [], ["CLS-TL-005"]) == []


def test_citing_a_clause_that_was_not_retrieved_fails():
    problems = check_draft(draft("ROUTE", ["CLS-TL-005"]), ROUTE_SIGNAL, [], ["CLS-COLL-001"])
    assert problems == ["cites CLS-TL-005, which no clause search returned in this run"]


def test_an_uncited_draft_fails_unless_it_is_a_deny_with_a_reason():
    assert check_draft(draft("ROUTE", []), ROUTE_SIGNAL, [], []) != []
    assert check_draft(draft("DENY", []), ROUTE_SIGNAL, [], []) != []
    assert check_draft(draft("DENY", [], deny_reason="no clause found"), ROUTE_SIGNAL, [], []) == []


def test_approve_fails_when_code_found_a_reason_not_to():
    problems = check_draft(draft("APPROVE", ["CLS-COLL-001"]), ROUTE_SIGNAL, [], ["CLS-COLL-001"])
    assert problems == ["APPROVE, but code found: total-loss candidate"]


def test_fallback_is_deny_when_nothing_can_be_cited():
    facts = {"net_payable_if_covered_usd": 1000, "loss_category": "collision"}
    fallback = fallback_draft(facts, ROUTE_SIGNAL, [], retrieved=[])
    assert fallback.outcome == "DENY"
    assert fallback.cited_clauses == []
    assert fallback.deny_reason == "no supporting policy clause was retrieved in this run"


def test_fallback_cites_only_retrieved_clauses():
    facts = {"net_payable_if_covered_usd": 1000, "loss_category": "collision"}
    fallback = fallback_draft(facts, ROUTE_SIGNAL, [], retrieved=["CLS-TL-005", "CLS-COLL-001"])
    assert fallback.outcome == "ROUTE"
    assert fallback.cited_clauses == ["CLS-TL-005"]


# --- the note write's retries -----------------------------------------------------

def test_note_write_retries_a_timeout_with_the_same_idempotency_key(monkeypatch):
    attempts = []

    def fake_post(url, json=None, headers=None, timeout=None):
        attempts.append(headers["Idempotency-Key"])
        if len(attempts) < 3:
            raise httpx.ReadTimeout("timed out")
        return httpx.Response(201, json={"note": {"note_id": 7}, "idempotent_replay": False})

    monkeypatch.setattr(api.httpx, "post", fake_post)
    waits = []
    client = api.ApiClient("token", base_url="http://api")
    response = client.write_note("CLM-1", {"run_id": "r"}, idempotency_key="key-1", sleep=waits.append)
    assert response["note"]["note_id"] == 7
    assert attempts == ["key-1", "key-1", "key-1"]
    assert 0.5 <= waits[0] <= 1.0 and 1.0 <= waits[1] <= 2.0   # 0.5 s then 1 s, each plus jitter


def test_note_write_does_not_retry_a_refusal(monkeypatch):
    attempts = []

    def fake_post(url, json=None, headers=None, timeout=None):
        attempts.append(1)
        return httpx.Response(409, json={"error": {"code": "idempotency_conflict", "message": "m"}})

    monkeypatch.setattr(api.httpx, "post", fake_post)
    client = api.ApiClient("token", base_url="http://api")
    with pytest.raises(api.ApiError) as refused:
        client.write_note("CLM-1", {"run_id": "r"}, idempotency_key="key-1", sleep=lambda s: None)
    assert refused.value.code == "idempotency_conflict"
    assert len(attempts) == 1
