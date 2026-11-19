"""End-to-end runs with the mock brain (run `make up` first).

    cd agent && uv run --extra dev pytest -q

Each run goes through everything real except the model: OBO tokens per agent, the MCP server
over HTTP (found through the registry), the API's access checks and audit log, the draft checks
and the note write.
"""
import asyncio

import pytest

from claimsense_agent.api import ApiClient
from claimsense_agent.pipeline import run_assessment
from conftest import RUN_IDS


def assess(live_api, user_id, group, claim_id, **options):
    from claimsense_api.auth import make_dev_token
    client = ApiClient(make_dev_token(user_id, group), base_url=live_api)
    result = asyncio.run(run_assessment(client, claim_id, brain="mock", **options))
    RUN_IDS.append(result.run_id)
    return result


def test_clean_claim_is_approved_with_retrieved_citations(live_api):
    from claimsense_api.db import fetch_all, fetch_one
    result = assess(live_api, "alice", "adjuster", "CLM-2024-3041")
    assert result.status == "written"
    assert result.outcome == "APPROVE"
    assert result.decision_source == "model"
    assert result.cited_clauses == ["CLS-COLL-001", "CLS-PER-006", "CLS-DED-004"]

    # every citation came back from a search in this run
    rows = fetch_all("SELECT clause_ids FROM claimsense.retrieval_log WHERE run_id = %s", (result.run_id,))
    retrieved = {c for row in rows for c in row["clause_ids"]}
    assert set(result.cited_clauses) <= retrieved

    note = fetch_one("SELECT * FROM claims_mgmt.claim_notes WHERE note_id = %s", (result.note_id,))
    assert note["outcome"] == "APPROVE"
    # CLM-2024-3041 is already Approved in the claims system: the note says this is a second opinion
    assert note["summary"].endswith("Second opinion: the claim was already Approved in the claims "
                                    "system when this assessment ran.")
    assessment = fetch_one("SELECT claim_status_at_run FROM claimsense.assessments WHERE run_id = %s",
                           (result.run_id,))
    assert assessment["claim_status_at_run"] == "Approved"


def test_each_agent_acted_for_alice_with_its_own_token(live_api):
    from claimsense_api.db import fetch_all
    result = assess(live_api, "alice", "adjuster", "CLM-2024-3041")
    rows = fetch_all("""SELECT DISTINCT actor FROM claimsense.audit_log
                        WHERE run_id = %s AND on_behalf_of = 'alice'""", (result.run_id,))
    assert sorted(r["actor"] for r in rows) == ["coverage", "drafter", "reader", "risk"]
    denied = fetch_all("""SELECT * FROM claimsense.audit_log
                          WHERE run_id = %s AND decision = 'deny'""", (result.run_id,))
    assert denied == []       # no agent tried anything outside its scopes


def test_an_agent_that_cannot_finish_leads_to_a_deny_note(live_api, monkeypatch):
    """The user's rule (2026-11-03): an agent failure is posted as a DENY for an adjuster to assess."""
    from claimsense_agent.agents import mock
    from claimsense_agent.tools import AgentFailed

    async def risk_runs_out_of_turns(tools, claim_id):
        await tools.call("get_claim", claim_id=claim_id)
        raise AgentFailed("risk: MaxTurnsExceeded: Max turns (15) exceeded")

    monkeypatch.setattr(mock, "risk", risk_runs_out_of_turns)
    result = assess(live_api, "alice", "adjuster", "CLM-2024-3041")
    assert result.status == "written" and result.note_id is not None
    assert result.outcome == "DENY"
    assert result.decision_source == "agent_failure"
    assert result.cited_clauses == []
    assert result.problems == ["risk: MaxTurnsExceeded: Max turns (15) exceeded"]


def test_coverage_citations_that_were_not_retrieved_are_removed(live_api, monkeypatch):
    from claimsense_agent.agents import mock
    real_coverage = mock.coverage

    async def coverage_citing_an_unretrieved_clause(tools, claim_id, facts):
        output = await real_coverage(tools, claim_id, facts)
        return output.model_copy(update={"cited_clauses": output.cited_clauses + ["CLS-PAY-012"]})

    monkeypatch.setattr(mock, "coverage", coverage_citing_an_unretrieved_clause)
    result = assess(live_api, "alice", "adjuster", "CLM-2024-3041")
    assert result.problems == ["coverage agent cited CLS-PAY-012, which no clause search returned "
                               "in this run; removed"]
    assert result.outcome == "APPROVE" and result.decision_source == "model"
    assert "CLS-PAY-012" not in result.cited_clauses


def test_lapsed_policy_is_denied(live_api):
    result = assess(live_api, "david", "adjuster", "CLM-2024-2822")
    assert result.outcome == "DENY"
    assert "CLS-PER-006" in result.cited_clauses


def test_adjuster_cannot_assess_someone_elses_claim(live_api):
    from claimsense_api.db import fetch_all
    result = assess(live_api, "alice", "adjuster", "CLM-2024-1873")      # carol's claim
    assert result.status == "failed"
    assert result.problems == ["claim not available (403 forbidden)"]
    issued = fetch_all("""SELECT * FROM claimsense.audit_log
                          WHERE action = 'issue_obo' AND run_id = %s""", (result.run_id,))
    assert issued == []       # no agent token was ever issued


def test_draft_citing_a_made_up_clause_is_denied(live_api):
    """The demo bad draft is an APPROVE citing CLS-XXX-999, which is not in the manual."""
    from claimsense_api.db import fetch_one
    result = assess(live_api, "alice", "adjuster", "CLM-2024-3041", bad_citation="CLS-XXX-999")
    assert result.status == "written"
    assert result.outcome == "DENY"
    assert result.decision_source == "deterministic_fallback"
    assert result.problems == ["cites CLS-XXX-999, which no clause search returned in this run",
                               "cites CLS-XXX-999, which does not exist in the policy manual"]
    assert result.cited_clauses == []
    note = fetch_one("SELECT deny_reason FROM claims_mgmt.claim_notes WHERE note_id = %s", (result.note_id,))
    assert note["deny_reason"] == "the draft cited CLS-XXX-999, which is not in the policy manual"


def test_precedence_picks_flag_and_the_note_lists_the_rest(live_api):
    """CLM-2024-1873 signals FLAG and ROUTE and has documentation gaps. FLAG wins (DENY > FLAG >
    ROUTE > APPROVE); code adds the senior-adjuster ROUTE and the gaps to the note."""
    from claimsense_api.db import fetch_one

    result = assess(live_api, "bob", "senior-adjuster", "CLM-2024-1873")
    assert result.outcome == "FLAG"
    assert "CLS-FRD-007" in result.cited_clauses
    note = fetch_one("SELECT summary FROM claims_mgmt.claim_notes WHERE note_id = %s", (result.note_id,))
    assert "Also needs: ROUTE: net payable" in note["summary"]
    assert "(CLS-PAY-012)" in note["summary"]
    assert "Pending documentation: no readable repair estimate (pending OCR) (CLS-DOC-009)" in note["summary"]
    assert "Code found no fraud indicators" not in note["summary"]      # this FLAG is for fraud


def test_an_agent_is_refused_outside_its_scopes(live_api):
    """The drafter's token has claim:read only, so reading the policy is refused by the API."""
    import uuid

    from claimsense_api.auth import make_dev_token
    from claimsense_agent.pipeline import run_agent
    from claimsense_agent.tools import ToolRefused

    async def nosy_drafter(tools, claim_id):
        return await tools.call("get_policy", claim_id=claim_id)

    client = ApiClient(make_dev_token("alice", "adjuster"), base_url=live_api)
    with pytest.raises(ToolRefused, match="get_policy refused"):
        asyncio.run(run_agent(client, "CLM-2024-1800", str(uuid.uuid4()), "drafter", nosy_drafter))


def test_the_batch_account_assesses_an_open_claim_for_its_adjuster(live_api):
    """The scheduled batch runs the same pipeline with the claimsense-batch token: the note is a
    draft for the assigned adjuster (alice), written by the batch."""
    from claimsense_api.db import fetch_one
    result = assess(live_api, "claimsense-batch", "batch-service", "CLM-2024-2165")
    assert result.status == "written", result.problems
    note = fetch_one("SELECT on_behalf_of, author FROM claims_mgmt.claim_notes WHERE note_id = %s",
                     (result.note_id,))
    assert note == {"on_behalf_of": "alice", "author": "claimsense-batch"}


def test_the_batch_account_cannot_assess_a_decided_claim(live_api):
    result = assess(live_api, "claimsense-batch", "batch-service", "CLM-2024-1800")
    assert result.status == "failed"
    assert result.problems == ["claim not available (403 forbidden)"]


def test_a_dry_run_checks_everything_but_writes_no_note(live_api):
    """The smoke test after an AgentCore deploy: the full run, as the batch account, no note."""
    from claimsense_api.db import fetch_one
    before = fetch_one("SELECT count(*) AS n FROM claims_mgmt.claim_notes WHERE claim_id = 'CLM-2024-2165'")["n"]
    result = assess(live_api, "claimsense-batch", "batch-service", "CLM-2024-2165", dry_run=True)
    assert result.status == "dry_run", result.problems
    assert result.outcome is not None
    assert result.decision_source == "model"
    assert result.note_id is None
    after = fetch_one("SELECT count(*) AS n FROM claims_mgmt.claim_notes WHERE claim_id = 'CLM-2024-2165'")["n"]
    assert after == before
