"""The Bedrock brain.

The first tests need no AWS. The last one calls Claude on Bedrock for real (about 40 s and a few
cents), so it runs only when asked:

    cd agent && CLAIMSENSE_BEDROCK_TESTS=1 AWS_PROFILE=claimsense uv run --extra dev pytest -q tests/test_bedrock.py
"""
import asyncio
import json
import os

import pytest

from claimsense_agent.agents import bedrock
from claimsense_agent.tools import ToolRefused
from conftest import RUN_IDS


class FakeTools:
    """Stands in for an agent's MCP session."""
    def __init__(self, refuse=False):
        self.refuse = refuse

    async def call(self, tool, **arguments):
        if self.refuse:
            raise ToolRefused(f"drafter: {tool} refused (403 forbidden)")
        return {"tool": tool, "arguments": arguments}


def test_tool_results_go_to_the_model_as_json():
    text = asyncio.run(bedrock.call_tool(FakeTools(), "get_claim", claim_id="CLM-2024-1800"))
    assert json.loads(text) == {"tool": "get_claim", "arguments": {"claim_id": "CLM-2024-1800"}}


def test_a_refusal_goes_to_the_model_as_data_not_an_error():
    text = asyncio.run(bedrock.call_tool(FakeTools(refuse=True), "get_policy", claim_id="CLM-2024-1800"))
    assert json.loads(text) == {"refused": "drafter: get_policy refused (403 forbidden)"}


def test_each_agent_gets_only_the_tools_it_names():
    tools = bedrock.make_tools(FakeTools(), ["get_claim", "search_clauses"])
    assert [t.name for t in tools] == ["get_claim", "search_clauses"]


def test_decisions_use_the_stronger_model_and_tracing_stays_off():
    assert "sonnet" in bedrock.MODELS["coverage"] and "sonnet" in bedrock.MODELS["drafter"]
    assert "haiku" in bedrock.MODELS["reader"] and "haiku" in bedrock.MODELS["risk"]
    assert os.environ["LITELLM_MODE"] == "PRODUCTION"      # no stray .env files loaded


@pytest.mark.skipif(os.environ.get("CLAIMSENSE_BEDROCK_TESTS") != "1",
                    reason="calls Claude on Bedrock; set CLAIMSENSE_BEDROCK_TESTS=1 to run")
def test_claude_assesses_the_clean_claim_and_passes_the_checks(live_api):
    from claimsense_api.auth import make_dev_token
    from claimsense_agent.api import ApiClient
    from claimsense_agent.pipeline import run_assessment

    client = ApiClient(make_dev_token("alice", "adjuster"), base_url=live_api)
    result = asyncio.run(run_assessment(client, "CLM-2024-1800", brain="bedrock"))
    RUN_IDS.append(result.run_id)
    assert result.status == "written", result.problems
    assert result.decision_source == "model"          # the draft passed every code check
    assert "CLS-COLL-001" in result.cited_clauses
    # Claude may APPROVE, or FLAG the location mismatch between the FNOL and the police report.
    # Expected outcomes per claim belong in the evaluation suite, not in this smoke test.
    assert result.outcome in ("APPROVE", "FLAG")
