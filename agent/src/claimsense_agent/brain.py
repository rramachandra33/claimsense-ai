"""The 'brain' switch: which agents think for the pipeline.

  * mock    — deterministic stand-ins (agents/mock.py). No model, no key, no AWS. The default,
              and what the tests and CI use.
  * bedrock — Claude on Amazon Bedrock through the OpenAI Agents SDK (agents/bedrock.py).
              Needs AWS credentials (locally AWS_PROFILE=claimsense) and costs a few cents a run.

Everything else in the pipeline (OBO tokens, MCP tools, code facts, checks, the note write) is
the same for both, so switching brains changes nothing around them.
"""
BRAINS = ("mock", "bedrock")


def agents_for(brain):
    """The four agent functions for a brain."""
    if brain == "mock":
        from .agents import mock as module
    elif brain == "bedrock":
        from .agents import bedrock as module      # imported only when used: it loads the SDK
    else:
        raise ValueError(f"brain must be one of {', '.join(BRAINS)}")
    return {"reader": module.reader, "coverage": module.coverage,
            "risk": module.risk, "drafter": module.drafter}


def models_for(brain):
    """Which model each agent ran on, recorded with every note."""
    if brain == "bedrock":
        from .agents.bedrock import MODELS
        return dict(MODELS)
    return {name: brain for name in ("reader", "coverage", "risk", "drafter")}
