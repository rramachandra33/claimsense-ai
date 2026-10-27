"""Mock agents: the real tool calls, with simple rules where the model's judgment will go.

Each function gets its agent's `AgentTools` (an MCP session under that agent's OBO token) and
returns the same typed output a real model will have to return. Nothing here needs a model,
a key or AWS, so a full run is free, fast and repeatable.

The mock agents cite a clause only when their own clause search returned it, exactly as a real
agent must.
"""
from ..facts import code_outcome, documentation_gaps, fraud_indicators, outcome_signals
from ..schemas import CoverageOutput, DraftOutput, ReaderOutput, RiskOutput

SUMMARY_LIMIT = 1000   # the note's summary limit in the API

# (search query, the clause the mock expects that search to support)
COVERAGE_SEARCHES = {
    "collision": ("collision coverage repair actual cash value", "CLS-COLL-001"),
    "comprehensive": ("comprehensive coverage theft vandalism fire flood", "CLS-COMP-002"),
    "period": ("policy period lapse expiration", "CLS-PER-006"),
    "liability_only": ("liability only own vehicle damage excluded", "CLS-LIAB-003"),
    "deductible": ("deductible", "CLS-DED-004"),
    "total_loss": ("total loss appraiser actual cash value", "CLS-TL-005"),
    "payment": ("payment authority senior adjuster confirmation", "CLS-PAY-012"),
    "injury": ("bodily injury police report medical report", "CLS-INJ-008"),
    "documents": ("documentation FNOL repair estimate OCR", "CLS-DOC-009"),
}
FRAUD_SEARCH = ("fraud misrepresentation staged loss SIU referral", "CLS-FRD-007")


async def search_and_cite(tools, query, clause_id, cited):
    """Search the manual; cite clause_id only if the search returned it."""
    await tools.call("search_clauses", query=query, top_k=4)
    if clause_id in tools.retrieved and clause_id not in cited:
        cited.append(clause_id)


async def reader(tools, claim_id):
    """1 · Read the file: every document's text, where OCR has finished."""
    claim = (await tools.call("get_claim", claim_id=claim_id))["claim"]
    documents = (await tools.call("list_documents", claim_id=claim_id))["documents"]

    read, unreadable, types = [], [], []
    for doc in documents:
        types.append(doc["document_type"])
        body = (await tools.call("get_document", document_id=doc["document_id"]))["document"]
        if body["ocr_text"]:
            read.append(doc["document_id"])
        else:
            unreadable.append(doc["document_id"])

    findings = []
    if "FNOL_FORM" not in types:
        findings.append("no first notice of loss on file")
    if "REPAIR_ESTIMATE" not in types:
        findings.append("no repair estimate on file")
    if unreadable:
        findings.append("text not available yet (OCR pending): " + ", ".join(unreadable))
    if "MEDICAL_REPORT" in types and not claim["injuries_reported"]:
        findings.append("medical report on a claim with no injuries reported")

    summary = (f"{claim['incident_type']} on {claim['incident_date']}: {claim['incident_description']} "
               f"{len(documents)} documents on file, {len(read)} read, {len(unreadable)} pending OCR.")
    return ReaderOutput(summary=summary, documents_read=read, documents_unreadable=unreadable,
                        findings=findings)


async def coverage(tools, claim_id, facts):
    """2 · Check coverage, using the code facts for dates and money."""
    claim = (await tools.call("get_claim", claim_id=claim_id))["claim"]
    policy = (await tools.call("get_policy", claim_id=claim_id))["policy"]

    wanted = ["comprehensive" if facts["loss_category"] == "comprehensive" else "collision", "period"]
    if policy["coverage_type"] == "Liability Only" or facts["coverage_purchased_for_loss"] is False:
        wanted.append("liability_only")
    if facts["coverage_purchased_for_loss"]:
        wanted.append("deductible")
    if facts["total_loss_candidate"]:
        wanted.append("total_loss")
    if facts["senior_confirmation_required"]:
        wanted.append("payment")
    if claim["injuries_reported"] or facts["documents"]["medical_report_on_no_injury_claim"]:
        wanted.append("injury")
    if not facts["documents"]["repair_estimate_readable"]:
        wanted.append("documents")

    cited = []
    for name in wanted:
        query, clause_id = COVERAGE_SEARCHES[name]
        await search_and_cite(tools, query, clause_id, cited)

    if not facts["in_force_at_loss"]:
        covered = False
        reasoning = f"Loss occurred {facts['days_after_policy_end']} days after the policy period ended."
    elif facts["coverage_purchased_for_loss"] is False:
        covered = False
        reasoning = f"The {policy['coverage_type']} policy has no {facts['loss_category']} cover."
    elif facts["coverage_purchased_for_loss"]:
        covered = True
        reasoning = (f"{facts['loss_category'].capitalize()} loss inside the policy period; "
                     f"deductible ${facts['deductible_usd']:,}, "
                     f"net payable if covered ${facts['net_payable_if_covered_usd']:,}.")
    else:
        covered = None
        reasoning = "The loss type does not map to collision or comprehensive; needs a person to decide."
    return CoverageOutput(covered=covered, reasoning=reasoning, cited_clauses=cited)


async def risk(tools, claim_id):
    """3 · Assess risk: the CLS-FRD-007 fraud indicators."""
    claim = (await tools.call("get_claim", claim_id=claim_id))["claim"]
    await tools.call("list_documents", claim_id=claim_id)
    indicators = fraud_indicators(claim)
    cited = []
    if indicators:
        query, clause_id = FRAUD_SEARCH
        await search_and_cite(tools, query, clause_id, cited)
    return RiskOutput(refer_to_siu=bool(indicators), indicators=indicators, cited_clauses=cited)


async def drafter(tools, claim_id, facts, reader_out, coverage_out, risk_out, demo_bad_draft=False):
    """4 · Draft the decision from the other agents' work and the code facts."""
    claim = (await tools.call("get_claim", claim_id=claim_id))["claim"]

    if demo_bad_draft:
        # A deliberately bad draft, to show the pipeline's checks replacing it.
        return DraftOutput(outcome="APPROVE", summary="Approve in full.", cited_clauses=["CLS-XXX-999"])

    signals = outcome_signals(claim, facts)
    gaps = documentation_gaps(facts)
    outcome = code_outcome(signals, gaps)
    # Cite what supports the outcome: for APPROVE the coverage clauses, otherwise the clause behind
    # each point raised. Only clauses the coverage and risk agents' searches returned can be cited.
    found = coverage_out.cited_clauses + risk_out.cited_clauses
    if outcome == "APPROVE":
        wanted = coverage_out.cited_clauses
    else:
        wanted = [s["clause"] for s in signals] + [g["clause"] for g in gaps]
    cited = []
    for clause in wanted:
        if clause in found and clause not in cited:
            cited.append(clause)

    reasons = [s["reason"] for s in signals] + [g["reason"] for g in gaps]
    deny_reason = None
    if outcome == "DENY":
        deny_reason = "; ".join(s["reason"] for s in signals if s["outcome"] == "DENY")

    lines = [f"Draft {outcome}, pending adjuster confirmation.", coverage_out.reasoning]
    if reasons:
        lines.append("Points for the adjuster: " + "; ".join(reasons) + ".")
    lines.append(reader_out.summary)
    summary = " ".join(lines)
    if len(summary) > SUMMARY_LIMIT:
        summary = summary[:SUMMARY_LIMIT - 1] + "…"
    return DraftOutput(outcome=outcome, summary=summary, cited_clauses=cited, deny_reason=deny_reason)
