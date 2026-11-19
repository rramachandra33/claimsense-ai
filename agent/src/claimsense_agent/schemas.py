"""Typed outputs: what each agent must return, and what one pipeline run produces.

The same models are used in mock mode and with a real model (as the Agents SDK `output_type`),
so the pipeline code never has to parse free text.
"""
from typing import Literal

from pydantic import BaseModel

Outcome = Literal["APPROVE", "FLAG", "ROUTE", "DENY"]


class ReaderOutput(BaseModel):
    """1 · Read the file: what the claim's documents say."""
    summary: str
    documents_read: list[str]           # document ids whose text was read
    documents_unreadable: list[str]     # OCR still pending, so no text yet
    findings: list[str]                 # e.g. "medical report on a claim with no injuries reported"


class CoverageOutput(BaseModel):
    """2 · Check coverage: is this loss covered, and which clauses say so."""
    covered: bool | None                # None when it cannot be decided from the file
    reasoning: str
    cited_clauses: list[str]


class RiskOutput(BaseModel):
    """3 · Assess risk: fraud indicators and whether to refer to the SIU."""
    refer_to_siu: bool
    indicators: list[str]
    cited_clauses: list[str]


class DraftOutput(BaseModel):
    """4 · Draft decision: the recommendation the adjuster will review."""
    outcome: Outcome
    summary: str
    cited_clauses: list[str]
    deny_reason: str | None = None


class RunResult(BaseModel):
    """What one pipeline run did."""
    run_id: str
    claim_id: str
    status: Literal["written", "replayed", "failed", "dry_run"]   # dry_run: checked, no note written
    outcome: Outcome | None = None
    decision_source: str | None = None  # "model" or "deterministic_fallback"
    cited_clauses: list[str] = []
    problems: list[str] = []            # why a draft was replaced, or why the run failed
    note_id: int | None = None
    input_tokens: int = 0               # model tokens across the four agents (0 for the mock brain)
    output_tokens: int = 0
    cost_usd: float | None = 0          # None if a model is missing from pricing.PRICES
