"""Tests for the batch loop: limits, budget, time and failures (no AWS, no API)."""
from claimsense_batch.handler import batch_token, run_batch


def answer(n, spent=0.0):
    claims = [{"claim_id": f"CLM-{i}", "reason": "never assessed"} for i in range(n)]
    return {"claims": claims, "needing_assessment": n, "spent_today_usd": spent}


def ok(claim_id):
    return {"claim_id": claim_id, "status": "written", "outcome": "FLAG", "cost_usd": 0.07}


def plenty_of_time():
    return 15 * 60 * 1000


def test_runs_every_picked_claim_within_the_limit():
    summary = run_batch(ok, answer(30), max_claims=25, budget_usd=5, parallel=3, time_left_ms=plenty_of_time)
    assert summary["picked"] == 25 and summary["runs"] == 25 and summary["failures"] == 0
    assert summary["cost_usd"] == 1.75 and summary["stopped"] is None


def test_stops_at_the_daily_budget():
    # $4.70 already spent today: room for 3 more runs at the $0.10 estimate
    summary = run_batch(ok, answer(10, spent=4.70), max_claims=25, budget_usd=5, parallel=3,
                        time_left_ms=plenty_of_time)
    assert summary["runs"] == 3 and summary["stopped"] == "daily budget reached"
    assert summary["not_run"] == 7


def test_stops_when_time_runs_out():
    calls = iter([15 * 60 * 1000, 60 * 1000])
    summary = run_batch(ok, answer(9), max_claims=25, budget_usd=5, parallel=3, time_left_ms=lambda: next(calls))
    assert summary["runs"] == 3 and summary["stopped"] == "out of time" and summary["not_run"] == 6


def test_a_failed_claim_does_not_stop_the_batch():
    def flaky(claim_id):
        if claim_id == "CLM-1":
            return {"claim_id": claim_id, "status": "error", "problems": ["ReadTimeoutError"]}
        return ok(claim_id)
    summary = run_batch(flaky, answer(4), max_claims=25, budget_usd=5, parallel=3, time_left_ms=plenty_of_time)
    assert summary["runs"] == 3 and summary["failures"] == 1


def test_the_token_is_for_the_batch_account(monkeypatch):
    import jwt
    monkeypatch.setenv("CLAIMSENSE_JWT_SECRET", "test-secret-for-pytest-only-0123456789abcdef")
    claims = jwt.decode(batch_token(), "test-secret-for-pytest-only-0123456789abcdef", algorithms=["HS256"])
    assert claims["sub"] == "claimsense-batch" and claims["cognito:groups"] == ["batch-service"]
    assert claims["exp"] - claims["iat"] == 3600
