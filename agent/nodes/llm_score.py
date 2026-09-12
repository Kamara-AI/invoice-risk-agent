"""llm_score node — LLM-powered composite risk scoring.

This node runs only when all 5 gates have passed. It calls the OpenAI LLM
(via LangChain) with a structured prompt that includes:
- The full parsed_invoice dict
- The list of gate_results (all passed, but may carry soft warnings in details)
- The vendor's trust_level and history from vendor_ledger
- Any contextual signals (e.g. invoice amount vs. vendor average)

The LLM must return a valid RiskScore (validated by Pydantic). If it does not,
we retry once with a stricter prompt before setting state.error.

Score thresholds (applied by the route node, not here):
- 0–49:  auto_approve
- 50–74: human_review
- 75+:   block
"""

from __future__ import annotations

from schemas.agent_state import AgentState


async def llm_score(state: AgentState) -> AgentState:
    """Generate a composite risk score for the invoice using the LLM.

    Args:
        state: Agent state with parsed_invoice and gate_results populated.

    Returns:
        Updated state with risk_score populated as a dict (RiskScore.model_dump()).
    """
    pass
