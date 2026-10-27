"""One assessment run, in the order code decides:

    code facts → reader → coverage → risk → drafter → check the draft → write the note

Code owns identity, access, dates and money. Each agent gets its own OBO token (one agent, one
claim, one run, five minutes) and reaches data only through the MCP server. The draft is
checked by code before anything is written:

  * every cited clause must have come back from a clause search in this run
  * a note must cite a clause, unless it is a DENY with a reason
  * APPROVE is not allowed when code found a reason not to approve

A draft that fails a check is replaced by code's own decision (decision_source
"deterministic_fallback"). If no clause can be cited at all, the outcome is DENY (open question 3).
The note is then written once, by code, with the adjuster's token and an Idempotency-Key.
"""
import uuid

from .api import ApiError
from .brain import agents_for
from .facts import (PROVISIONAL_PRECEDENCE, code_outcome, compute_facts, documentation_gaps,
                    outcome_signals)
from .schemas import DraftOutput, RunResult
from .tools import ToolRefused, open_tools
from .trace import Tracer

# The clauses an APPROVE rests on, by loss category: the insuring clause, deductible and period.
APPROVE_CLAUSES = {
    "collision": ["CLS-COLL-001", "CLS-DED-004", "CLS-PER-006"],
    "comprehensive": ["CLS-COMP-002", "CLS-DED-004", "CLS-PER-006"],
}


async def run_agent(client, claim_id, run_id, agent, agent_function, *inputs, **options):
    """Get the agent's OBO token, start its MCP server with it, and run the agent.

    Returns (output, clause ids its searches returned). A refusal is raised only after the MCP
    session has closed, so it arrives as a plain ToolRefused, not wrapped by the session.
    """
    token = client.obo_token(claim_id, agent, run_id)
    refused = None
    async with open_tools(agent, token, run_id) as tools:
        try:
            output = await agent_function(tools, claim_id, *inputs, **options)
        except ToolRefused as e:
            refused = e
    if refused:
        raise refused
    return output, tools.retrieved


def check_draft(draft, signals, gaps, retrieved):
    """The code checks on a draft. Returns a list of problems; empty means the draft passes."""
    problems = []
    for clause in draft.cited_clauses:
        if clause not in retrieved:
            problems.append(f"cites {clause}, which no clause search returned in this run")
    if not draft.cited_clauses and not (draft.outcome == "DENY" and draft.deny_reason):
        problems.append("cites no clause and is not a DENY with a reason")
    if draft.outcome == "DENY" and not draft.deny_reason:
        problems.append("DENY without a deny_reason")
    if draft.outcome == "APPROVE" and (signals or gaps):
        reasons = [s["reason"] for s in signals] + [g["reason"] for g in gaps]
        problems.append("APPROVE, but code found: " + "; ".join(reasons))
    return problems


def fallback_draft(facts, signals, gaps, retrieved):
    """Code's own draft, used when the agents' draft fails a check."""
    outcome = code_outcome(signals, gaps)
    reasons = [s for s in signals if s["outcome"] == outcome]
    if outcome == "FLAG":
        reasons = reasons + gaps
    if outcome == "APPROVE":
        cited = [c for c in APPROVE_CLAUSES.get(facts["loss_category"], []) if c in retrieved]
    else:
        cited = [r["clause"] for r in reasons if r["clause"] in retrieved]
    reason_text = "; ".join(r["reason"] for r in reasons)

    if not cited:
        # Open question 3 (confirmed): no supporting clause found means DENY, never an uncited note.
        return DraftOutput(outcome="DENY", cited_clauses=[],
                           deny_reason="no supporting policy clause was retrieved in this run",
                           summary="Draft DENY by code: no supporting policy clause was retrieved "
                                   "in this run, so no other outcome can be cited. Needs adjuster review.")
    summary = f"Draft {outcome} by code (the agents' draft failed a check), pending adjuster confirmation."
    if reason_text:
        summary += " " + reason_text + "."
    if facts["net_payable_if_covered_usd"] is not None:
        summary += f" Net payable if covered ${facts['net_payable_if_covered_usd']:,}."
    return DraftOutput(outcome=outcome, summary=summary, cited_clauses=cited,
                       deny_reason=reason_text if outcome == "DENY" else None)


async def run_assessment(client, claim_id, brain="mock", tracer=None, demo_bad_draft=False):
    """Run the four agents on one claim and write the draft note. Returns a RunResult."""
    tracer = tracer or Tracer()
    run_id = str(uuid.uuid4())
    result = RunResult(run_id=run_id, claim_id=claim_id, status="failed")
    agents = agents_for(brain)

    # ---- code facts (adjuster's token; the access check happens here first) -------------------
    with tracer.span("code facts", kind="tool") as t:
        try:
            claim, policy, documents = client.claim_file(claim_id)
        except ApiError as e:
            t.event(f"claim not available: {e.code}", level="block")
            result.problems.append(f"claim not available ({e.status} {e.code})")
            return result
        facts = compute_facts(claim, policy, documents)
        signals = outcome_signals(claim, facts)
        gaps = documentation_gaps(facts)
        t.kv("in force at loss", facts["in_force_at_loss"])
        t.kv("net payable", facts["net_payable_if_covered_usd"])
        for s in signals:
            t.event(f"{s['outcome']}: {s['reason']} ({s['clause']})", level="warn")
        for g in gaps:
            t.event(f"gap: {g['reason']} ({g['clause']})", level="warn")

    # ---- the four agents, in order ------------------------------------------------------------
    outputs, retrieved = {}, []
    try:
        with tracer.span("reader", kind="agent") as t:
            outputs["reader"], _ = await run_agent(client, claim_id, run_id, "reader", agents["reader"])
            t.event(outputs["reader"].summary)

        with tracer.span("coverage", kind="agent") as t:
            outputs["coverage"], found = await run_agent(client, claim_id, run_id, "coverage",
                                                         agents["coverage"], facts)
            retrieved += found
            t.kv("covered", outputs["coverage"].covered)
            t.kv("cites", outputs["coverage"].cited_clauses)

        with tracer.span("risk", kind="agent") as t:
            outputs["risk"], found = await run_agent(client, claim_id, run_id, "risk", agents["risk"])
            retrieved += found
            t.kv("refer to SIU", outputs["risk"].refer_to_siu)

        with tracer.span("drafter", kind="agent") as t:
            outputs["drafter"], _ = await run_agent(
                client, claim_id, run_id, "drafter", agents["drafter"],
                facts, outputs["reader"], outputs["coverage"], outputs["risk"],
                demo_bad_draft=demo_bad_draft)
            t.kv("outcome", outputs["drafter"].outcome)
            t.kv("cites", outputs["drafter"].cited_clauses)
    except (ToolRefused, ApiError) as e:
        result.problems.append(str(e))
        return result

    # ---- code checks the draft ------------------------------------------------------------------
    with tracer.span("check draft", kind="guardrail") as t:
        draft = outputs["drafter"]
        problems = check_draft(draft, signals, gaps, retrieved)
        decision_source = "model"
        if problems:
            for p in problems:
                t.event(p, level="block")
            draft = fallback_draft(facts, signals, gaps, retrieved)
            decision_source = "deterministic_fallback"
            t.event(f"replaced by code's draft: {draft.outcome}", level="warn")
        else:
            t.event("draft passes every check", level="ok")

    # ---- code writes the note (adjuster's token, idempotent) ----------------------------------
    note = {
        "run_id": run_id,
        "outcome": draft.outcome,
        "summary": draft.summary,
        "cited_clauses": draft.cited_clauses,
        "deny_reason": draft.deny_reason,
        "decision_source": decision_source,
        "code_facts": {"facts": facts, "signals": signals, "documentation_gaps": gaps,
                       "provisional_precedence": PROVISIONAL_PRECEDENCE},
        "agent_outputs": {name: out.model_dump() for name, out in outputs.items()},
        "models": {name: brain for name in outputs},
    }
    note["agent_outputs"]["draft_problems"] = problems
    with tracer.span("write note", kind="tool") as t:
        try:
            response = client.write_note(claim_id, note, idempotency_key=run_id)
        except ApiError as e:
            t.event(f"refused: {e}", level="block")
            result.problems.append(f"note not written ({e.status} {e.code})")
            return result
        result.note_id = response["note"]["note_id"]
        t.event(f"note {result.note_id} written", level="ok")

    result.status = "replayed" if response["idempotent_replay"] else "written"
    result.outcome = draft.outcome
    result.decision_source = decision_source
    result.cited_clauses = draft.cited_clauses
    result.problems = problems
    return result
