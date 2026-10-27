"""The 'brain' switch: which agents think for the pipeline.

  * mock    — deterministic stand-ins (agents/mock.py). No model, no key, no AWS. The default,
              and what the tests and CI use.
  * bedrock — Claude on Amazon Bedrock through the OpenAI Agents SDK (next step, not built yet).

Everything else in the pipeline (OBO tokens, MCP tools, code facts, checks, the note write) is
the same for both, so switching brains changes nothing around them.
"""
BRAINS = ("mock", "bedrock")


def agents_for(brain):
    """The four agent functions for a brain."""
    if brain == "mock":
        from .agents import mock
        return {"reader": mock.reader, "coverage": mock.coverage,
                "risk": mock.risk, "drafter": mock.drafter}
    if brain == "bedrock":
        raise NotImplementedError("The Bedrock brain is the next step; run with --brain mock for now.")
    raise ValueError(f"brain must be one of {', '.join(BRAINS)}")
