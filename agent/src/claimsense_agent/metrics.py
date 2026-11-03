"""Metrics to Amazon CloudWatch (namespace ClaimSense), for the three dashboards:

  experience  RunDurationMs (p50/p95), Runs, Failures
  economics   RunCostUsd, InputTokens, OutputTokens, Resolutions (a run that writes a note), so
              cost per resolution = sum of RunCostUsd / sum of Resolutions
  quality     Fallbacks (the draft failed a check and code's decision was used), Decisions by
              outcome, and EvalPassRate from the evaluation suite

Off unless CLAIMSENSE_METRICS=1 (the AgentCore runtime and CI set it). Publishing never breaks a
run: a failure is printed and the run's answer is returned as usual.
"""
import os

NAMESPACE = "ClaimSense"


def metrics_on():
    return os.environ.get("CLAIMSENSE_METRICS") == "1"


def metric(name, value, unit="Count", **dimensions):
    """One CloudWatch data point, in the shape PutMetricData takes."""
    return {"MetricName": name, "Value": value, "Unit": unit,
            "Dimensions": [{"Name": key, "Value": str(val)} for key, val in dimensions.items()]}


def run_metrics(result, duration_ms, brain):
    """The data points for one assessment run (result is a RunResult)."""
    points = [
        metric("Runs", 1, Brain=brain),
        metric("RunDurationMs", duration_ms, "Milliseconds", Brain=brain),
        metric("Failures", 1 if result.status == "failed" else 0, Brain=brain),
        metric("Resolutions", 1 if result.note_id is not None else 0, Brain=brain),
        metric("Fallbacks", 1 if result.decision_source == "deterministic_fallback" else 0, Brain=brain),
        metric("InputTokens", result.input_tokens, Brain=brain),
        metric("OutputTokens", result.output_tokens, Brain=brain),
    ]
    if result.cost_usd is not None:
        points.append(metric("RunCostUsd", result.cost_usd, "None", Brain=brain))
    if result.outcome:
        points.append(metric("Decisions", 1, Brain=brain, Outcome=result.outcome))
    return points


def eval_metrics(summary):
    """The data points for one full evaluation run (summary from evaluate.summarise)."""
    brain = summary["brain"]
    return [
        metric("EvalPassRate", summary["pass_rate"] * 100, "Percent", Brain=brain),
        metric("EvalCases", summary["cases"], Brain=brain),
        metric("EvalCostUsd", summary["cost_usd"], "None", Brain=brain),
    ]


def publish(points):
    """Send the data points to CloudWatch. Returns True if they were sent."""
    try:
        import boto3

        client = boto3.client("cloudwatch", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        client.put_metric_data(Namespace=NAMESPACE, MetricData=points)
        return True
    except Exception as e:
        print(f"[metrics] not published: {type(e).__name__}: {e}")
        return False
