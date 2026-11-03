"""The CloudWatch metrics: what one run and one evaluation send (no AWS needed)."""
from claimsense_agent import metrics
from claimsense_agent.schemas import RunResult


def values(points):
    """{metric name: value}, plus Decisions as Decisions:<outcome>."""
    out = {}
    for p in points:
        name = p["MetricName"]
        if name == "Decisions":
            name += ":" + [d["Value"] for d in p["Dimensions"] if d["Name"] == "Outcome"][0]
        out[name] = p["Value"]
    return out


def test_a_written_run_is_a_resolution():
    result = RunResult(run_id="r", claim_id="c", status="written", outcome="APPROVE",
                       decision_source="model", note_id=7, input_tokens=100, output_tokens=20,
                       cost_usd=0.07)
    got = values(metrics.run_metrics(result, 54000, "bedrock"))
    assert got == {"Runs": 1, "RunDurationMs": 54000, "Failures": 0, "Resolutions": 1, "Fallbacks": 0,
                   "AgentFailures": 0, "InputTokens": 100, "OutputTokens": 20, "RunCostUsd": 0.07, "Decisions:APPROVE": 1}


def test_a_fallback_and_a_failure_are_counted():
    fallback = RunResult(run_id="r", claim_id="c", status="written", outcome="DENY",
                         decision_source="deterministic_fallback", note_id=8)
    assert values(metrics.run_metrics(fallback, 1, "mock"))["Fallbacks"] == 1
    failed = RunResult(run_id="r", claim_id="c", status="failed", problems=["claim not available"])
    got = values(metrics.run_metrics(failed, 1, "mock"))
    assert got["Failures"] == 1 and got["Resolutions"] == 0
    assert not any(k.startswith("Decisions") for k in got)


def test_every_point_carries_the_brain():
    result = RunResult(run_id="r", claim_id="c", status="written", outcome="FLAG", note_id=1)
    for point in metrics.run_metrics(result, 1, "bedrock"):
        assert {"Name": "Brain", "Value": "bedrock"} in point["Dimensions"]


def test_eval_pass_rate_is_a_percentage():
    summary = {"brain": "mock", "pass_rate": 0.967, "cases": 60, "cost_usd": 0}
    assert values(metrics.eval_metrics(summary))["EvalPassRate"] == 96.7


def test_off_unless_switched_on(monkeypatch):
    monkeypatch.delenv("CLAIMSENSE_METRICS", raising=False)
    assert not metrics.metrics_on()
    monkeypatch.setenv("CLAIMSENSE_METRICS", "1")
    assert metrics.metrics_on()


def test_a_publishing_failure_does_not_raise(monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("no credentials")
    monkeypatch.setattr("boto3.client", broken)
    assert metrics.publish([metrics.metric("Runs", 1, Brain="mock")]) is False


def test_tracer_spans_are_opentelemetry_spans():
    """Each Tracer span is also an OpenTelemetry span, nested the same way."""
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from claimsense_agent import trace

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.OTEL_TRACER = provider.get_tracer("claimsense")
    try:
        tracer = trace.Tracer(quiet=True)
        with tracer.span("reader", kind="agent"):
            with tracer.span("get_claim", kind="tool"):
                pass
    finally:
        trace.OTEL_TRACER = trace.otel_trace.get_tracer("claimsense")
    spans = {s.name: s for s in exporter.get_finished_spans()}
    assert spans["reader"].attributes["claimsense.kind"] == "agent"
    assert spans["get_claim"].parent.span_id == spans["reader"].context.span_id
