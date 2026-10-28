"""Token costs. No database, API or AWS needed."""
import pytest

from claimsense_agent.pricing import cost_usd, usage_summary

HAIKU = "bedrock/converse/us.anthropic.claude-haiku-4-5-20251001-v1:0"
SONNET = "bedrock/converse/us.anthropic.claude-sonnet-4-5-20250929-v1:0"


def test_cost_uses_the_us_profile_prices():
    # Haiku: $1.10 in, $5.50 out per million tokens; Sonnet: $3.30 in, $16.50 out
    assert cost_usd(HAIKU, 1_000_000, 0) == pytest.approx(1.10)
    assert cost_usd(HAIKU, 0, 1_000_000) == pytest.approx(5.50)
    assert cost_usd(SONNET, 10_000, 1_000) == pytest.approx(0.033 + 0.0165)


def test_unknown_model_has_no_price():
    assert cost_usd("bedrock/converse/some-other-model", 1000, 1000) is None


def test_run_totals_add_up_the_agents():
    per_agent = {
        "reader": {"model": HAIKU, "input_tokens": 10_000, "output_tokens": 500, "cost_usd": 0.01375},
        "drafter": {"model": SONNET, "input_tokens": 5_000, "output_tokens": 400, "cost_usd": 0.0231},
    }
    totals = usage_summary(per_agent)
    assert totals["input_tokens"] == 15_000
    assert totals["output_tokens"] == 900
    assert totals["cost_usd"] == pytest.approx(0.0369, abs=0.0001)


def test_mock_runs_cost_nothing_and_unknown_prices_stay_unknown():
    assert usage_summary({})["cost_usd"] == 0
    unknown = {"reader": {"model": "x", "input_tokens": 1, "output_tokens": 1, "cost_usd": None}}
    assert usage_summary(unknown)["cost_usd"] is None
