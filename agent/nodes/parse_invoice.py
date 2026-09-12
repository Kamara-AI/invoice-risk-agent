"""parse_invoice node — extract structured data from a raw PDF invoice.

Responsibility:
- Read raw_pdf_bytes from state.
- Use PyPDF2 to extract text, then call the LLM to parse it into a ParsedInvoice.
- Write the result to state.parsed_invoice as a dict (model_dump()).
- Clear raw_pdf_bytes after parsing to avoid carrying large payloads downstream.
- On failure, set state.error and return immediately (the graph will dead-letter).
"""

from __future__ import annotations

from schemas.agent_state import AgentState


async def parse_invoice(state: AgentState) -> AgentState:
    """Extract and validate invoice fields from the raw PDF attachment.

    This node is the only place in the graph that touches raw_pdf_bytes.
    All downstream nodes work exclusively with parsed_invoice (a dict).

    Args:
        state: Agent state containing raw_pdf_bytes and gmail_message_id.

    Returns:
        Updated state with parsed_invoice populated and raw_pdf_bytes cleared.
    """
    pass
