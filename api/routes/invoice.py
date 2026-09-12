"""Invoice processing route.

POST /invoices/process-invoice

Accepts a multipart form upload containing:
- A PDF file (the invoice attachment)
- InvoiceInput metadata as a JSON body field

Builds initial AgentState, invokes the compiled LangGraph graph, and returns
the routing decision. The graph handles all side-effects (Slack, Supabase, Gmail).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile

from agent.graph import build_graph
from schemas.invoice import InvoiceInput

router = APIRouter()

# Compiled graph is built once when the module loads — not per request.
# build_graph() compiles the StateGraph; the result is stateless and reusable.
_graph = build_graph()


@router.post("/process-invoice")
async def process_invoice(
    invoice_metadata: str,
    pdf_file: UploadFile,
) -> dict:
    """Receive an invoice PDF and run it through the risk agent pipeline.

    Args:
        invoice_metadata: JSON string conforming to InvoiceInput schema,
                          submitted as a form field named 'invoice_metadata'.
        pdf_file: The PDF invoice attachment as a multipart file upload.

    Returns:
        A dict containing invoice_id, routing_decision, risk_score, and
        gate_results for the caller's reference.

    Raises:
        HTTPException 422: If invoice_metadata fails Pydantic validation.
        HTTPException 500: If the agent graph encounters an unhandled error.
    """
    pass
