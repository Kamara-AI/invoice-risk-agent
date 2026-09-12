"""Gate result schema.

Each of the five validation gates (quality, math, duplicate, ofac, stripe)
appends one GateResult to AgentState.gate_results before exiting.
The list is never modified after being written — it is an append-only audit trail.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class GateResult(BaseModel):
    """Outcome of a single fraud-detection gate.

    Gate nodes must always produce a GateResult — even on internal error —
    so the audit log always has a complete picture of what ran and why.
    """

    gate_name: str = Field(
        ...,
        description=(
            "Canonical name of the gate that produced this result. "
            "One of: 'quality', 'math', 'duplicate', 'ofac', 'stripe'."
        ),
    )
    passed: bool = Field(
        ...,
        description="True if the invoice cleared this gate; False if it was flagged.",
    )
    reason: str = Field(
        ...,
        description="Human-readable summary of why the gate passed or failed.",
    )
    details: dict | None = Field(
        default=None,
        description=(
            "Structured supporting data (e.g. API response excerpts, calculated values). "
            "Optional but strongly encouraged for gates that call external APIs."
        ),
    )
    checked_at: str = Field(
        ...,
        description="ISO-8601 timestamp (EAT / UTC+3) at which this gate completed.",
    )
