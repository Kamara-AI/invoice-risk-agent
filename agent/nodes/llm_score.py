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
- 50–89: human_review
- 90+:   block
"""

from __future__ import annotations

import json
import logging

from langchain_openai import ChatOpenAI

from config import settings
from db.queries import get_vendor_by_name
from schemas.agent_state import AgentState
from schemas.risk import RiskScore
from utils import now_eat

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are an expert accounts payable fraud analyst. Your job is to
assess the risk of a vendor invoice and return a structured risk score.

You will be given:
1. The parsed invoice data
2. The results from 5 automated fraud-detection gates (all passed — no hard failures)
3. The vendor's historical trust level and OFAC status

IMPORTANT: All 5 gates have already passed. You are scoring residual soft risk only.
Do NOT re-flag things the gates already cleared. A gate pass is a positive signal.

Score the invoice on a scale of 0-100:
- 0-49:  Low risk — auto_approve (routine invoice, no significant soft signals)
- 50-89: Medium-high risk — human_review (notable soft signals warranting a second look)
- 90-100: Block — only for extraordinary risk signals not caught by the gates

Scoring guidance:
- OFAC soft flag in gate_results (tier='soft_flag'): +35 to +40 points — this alone should push to human_review
- Known/trusted vendor (trust_level='trusted' or seen_before=True) with PO reference: start at 10, high amounts are normal — do NOT add points just for invoice size if vendor is known
- New vendor (trust_level='new') with LOW invoice amount (<$20k), with or without PO: +5 to +10 points ONLY — amount is too small to warrant review for a missing PO
- New vendor with MODERATE invoice amount ($20k-$50k), no PO: +10 to +15 points
- New vendor with HIGH invoice amount (>$50k) AND no PO: +20 to +30 points
- New vendor with HIGH invoice amount (>$50k) WITH PO reference: +10 to +15 points
- Normal business invoice, all gates pass, complete fields, PO reference: score 10-30 → auto_approve
- Backdated >60 days: +15 points
- No PO reference on high-value invoice (>$50k) from NEW vendor: +10 points (already included above)

Most legitimate invoices that pass all 5 gates should score 10-45 and auto_approve.
Reserve human_review (50+) for genuinely ambiguous cases. Reserve block (90+) for
extraordinary circumstances — the gates handle hard fraud; you handle soft risk.
"""

def _get_llm():
    """Lazy-init the primary LLM so OPENAI_API_KEY is not required at import time."""
    return ChatOpenAI(
        model="gpt-4o", temperature=0, api_key=settings.openai_api_key
    ).with_structured_output(RiskScore)


def _get_llm_strict():
    """Lazy-init the strict-mode LLM for retry attempts."""
    return ChatOpenAI(
        model="gpt-4o", temperature=0, api_key=settings.openai_api_key
    ).with_structured_output(RiskScore, strict=True)


async def llm_score(state: AgentState) -> AgentState:
    """Generate a composite risk score for the invoice using the LLM.

    Args:
        state: Agent state with parsed_invoice and gate_results populated.

    Returns:
        Updated state with risk_score populated as a dict (RiskScore.model_dump()).
    """
    parsed = state.get("parsed_invoice") or {}
    gate_results = state.get("gate_results") or []

    # Fetch vendor history to provide context to the LLM.
    vendor_name = parsed.get("vendor_name", "")
    vendor_context: dict = {"trust_level": "new", "ofac_status": "unchecked", "seen_before": False}
    try:
        vendor = get_vendor_by_name(vendor_name)
        if vendor:
            vendor_context = {
                "trust_level": vendor.get("trust_level", "new"),
                "ofac_status": vendor.get("ofac_status", "unchecked"),
                "radar_score_history": vendor.get("radar_score"),
                "first_seen": str(vendor.get("first_seen", "")),
                "last_seen": str(vendor.get("last_seen", "")),
                "seen_before": True,
            }
    except Exception as exc:
        logger.warning("llm_score: vendor lookup failed: %s", exc)

    user_content = (
        f"**Invoice Data:**\n{json.dumps(parsed, indent=2, default=str)}\n\n"
        f"**Gate Results (all passed):**\n{json.dumps(gate_results, indent=2, default=str)}\n\n"
        f"**Vendor History:**\n{json.dumps(vendor_context, indent=2)}\n\n"
        f"**Timestamp:** {now_eat()}\n\n"
        "Please assess the risk and return a RiskScore."
    )

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    try:
        score: RiskScore = await _get_llm().ainvoke(messages)
        state["risk_score"] = score.model_dump()
    except Exception as first_exc:
        logger.warning("llm_score: first attempt failed (%s), retrying with strict mode", first_exc)
        try:
            score = await _get_llm_strict().ainvoke(messages)
            state["risk_score"] = score.model_dump()
        except Exception as second_exc:
            state["error"] = f"llm_score: structured output failed after retry: {second_exc}"

    return state
