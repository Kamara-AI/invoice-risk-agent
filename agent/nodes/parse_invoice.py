"""parse_invoice node — extract structured data from a raw PDF invoice.

Responsibility:
- Read raw_pdf_bytes from state.
- Use pypdf to extract text, then call the LLM to parse it into a ParsedInvoice.
- Write the result to state.parsed_invoice as a dict (model_dump()).
- Clear raw_pdf_bytes after parsing to avoid carrying large payloads downstream.
- On failure, set state.error and return immediately (the graph will dead-letter).
"""

from __future__ import annotations

import io

import pypdf
from langchain_openai import ChatOpenAI

from config import settings
from schemas.agent_state import AgentState
from schemas.invoice import ParsedInvoice

_SYSTEM_PROMPT = (
    "You are an invoice parser. Extract all fields from the following invoice text "
    "and return a valid ParsedInvoice JSON. Be precise with numbers — do not round "
    "or estimate. If a field is not present in the text, omit it or set it to null "
    "where the schema allows. Always extract vendor_bank_account if any bank/payment "
    "details appear in the document."
)


def _get_llm():
    """Lazy-init the LLM so we don't require OPENAI_API_KEY at import time."""
    return ChatOpenAI(
        model="gpt-4o-mini", temperature=0, api_key=settings.openai_api_key
    ).with_structured_output(ParsedInvoice)


async def parse_invoice(state: AgentState) -> AgentState:
    """Extract and validate invoice fields from the raw PDF attachment.

    This node is the only place in the graph that touches raw_pdf_bytes.
    All downstream nodes work exclusively with parsed_invoice (a dict).

    Args:
        state: Agent state containing raw_pdf_bytes and gmail_message_id.

    Returns:
        Updated state with parsed_invoice populated and raw_pdf_bytes cleared.
    """
    try:
        raw_bytes = state.get("raw_pdf_bytes")
        if not raw_bytes:
            state["error"] = "parse_invoice: raw_pdf_bytes is missing or empty"
            return state

        # Extract all text from the PDF pages.
        reader = pypdf.PdfReader(io.BytesIO(raw_bytes))
        pages_text = "\n\n".join(
            page.extract_text() or "" for page in reader.pages
        )

        if not pages_text.strip():
            state["error"] = "parse_invoice: extracted PDF text is empty — may be a scanned image"
            return state

        # LLM structured extraction — raises if schema validation fails.
        _llm = _get_llm()
        parsed: ParsedInvoice = await _llm.ainvoke(
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": pages_text},
            ]
        )

        state["parsed_invoice"] = parsed.model_dump(mode="json")
        state["raw_pdf_bytes"] = None  # Free memory — not needed downstream.

    except Exception as exc:
        state["error"] = f"parse_invoice: {exc}"

    return state
