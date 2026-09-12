"""Risk scoring and routing decision schemas.

Produced by the llm_score node and consumed by the route node.
The LLM must return output that validates against RiskScore — if it doesn't,
the node raises and the graph routes to the dead-letter path.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RiskScore(BaseModel):
    """LLM-generated risk assessment for a parsed invoice.

    The score is a composite of gate results, vendor history, and contextual
    reasoning. The LLM is the final arbiter of score and recommendation;
    the route node applies business-rule thresholds on top.
    """

    score: int = Field(
        ...,
        ge=0,
        le=100,
        description=(
            "Composite risk score from 0 (lowest risk) to 100 (highest risk). "
            "Scores ≥ 70 trigger human_review; ≥ 90 trigger block."
        ),
    )
    flags: list[str] = Field(
        default_factory=list,
        description=(
            "Ordered list of risk signals surfaced during scoring. "
            "Each flag is a short, human-readable string (e.g. 'math_mismatch', 'ofac_hit')."
        ),
    )
    reasoning: str = Field(
        ...,
        description=(
            "Free-text explanation of how the score was derived. "
            "This text is included verbatim in the Slack review request."
        ),
    )
    recommendation: Literal["auto_approve", "human_review", "block"] = Field(
        ...,
        description=(
            "LLM's recommended action before business-rule thresholds are applied. "
            "The route node may upgrade (never downgrade) this recommendation."
        ),
    )


class RoutingDecision(BaseModel):
    """Final routing outcome written to state and persisted to invoice_history.

    Produced by the route node after applying business-rule thresholds to
    the LLM's RiskScore recommendation.
    """

    action: Literal["auto_approve", "human_review", "block"] = Field(
        ...,
        description="Final action taken on this invoice after all rules are applied.",
    )
    reason: str = Field(
        ...,
        description="Explanation of why this action was chosen, suitable for audit logs.",
    )
    invoice_id: str = Field(..., description="Invoice run ID this decision applies to.")
    risk_score: int = Field(..., ge=0, le=100, description="The score that drove this decision.")
