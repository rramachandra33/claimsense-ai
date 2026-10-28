"""End-to-end runs with the mock brain (run `make up` first).

    cd agent && uv run --extra dev pytest -q

Each run goes through everything real except the model: OBO tokens per agent, the MCP server
over stdio, the API's access checks and audit log, the draft checks and the note write.
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
    result = assess(live_api, "alice", "adjuster", "CLM-2024-1800")
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


def test_each_agent_acted_for_alice_with_its_own_token(live_api):
    from claimsense_api.db import fetch_all
    result = assess(live_api, "alice", "adjuster", "CLM-2024-1800")
    rows = fetch_all("""SELECT DISTINCT actor FROM claimsense.audit_log
                        WHERE run_id = %s AND on_behalf_of = 'alice'""", (result.run_id,))
    assert sorted(r["actor"] for r in rows) == ["coverage", "drafter", "reader", "risk"]
    denied = fetch_all("""SELECT * FROM claimsense.audit_log
                          WHERE run_id = %s AND decision = 'deny'""", (result.run_id,))
    assert denied == []       # no agent tried anything outside its scopes


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
    result = assess(live_api, "alice", "adjuster", "CLM-2024-1800", demo_bad_draft=True)
    assert result.status == "written"
    assert result.outcome == "DENY"
    assert result.decision_source == "deterministic_fallback"
    assert result.problems == ["cites CLS-XXX-999, which no clause search returned in this run",
                               "cites CLS-XXX-999, which does not exist in the policy manual"]
    assert result.cited_clauses == []
    note = fetch_one("SELECT deny_reason FROM claims_mgmt.claim_notes WHERE note_id = %s", (result.note_id,))
    assert note["deny_reason"] == "the draft cited CLS-XXX-999, which is not in the policy manual"


def test_precedence_case_uses_the_provisional_order(live_api):
    """CLM-2024-1873 signals FLAG and ROUTE (evals/precedence_cases.json). Until open question 2 is
    decided, the provisional order picks FLAG; update this test when precedence is set."""
    result = assess(live_api, "bob", "senior-adjuster", "CLM-2024-1873")
    assert result.outcome == "FLAG"
    assert "CLS-FRD-007" in result.cited_clauses
    assert "CLS-PAY-012" in result.cited_clauses


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
