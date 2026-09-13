"""Invoice processing route.

POST /invoices/process-invoice

Accepts a multipart form upload containing:
- A PDF file (the invoice attachment)
- InvoiceInput metadata as a JSON body field

Builds initial AgentState, invokes the compiled LangGraph graph, and returns
the routing decision. The graph handles all side-effects (Slack, Supabase, Gmail).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from agent.graph import build_graph
from schemas.invoice import InvoiceInput
from utils import now_eat

router = APIRouter()

# Compiled graph is built once when the module loads — not per request.
# build_graph() compiles the StateGraph; the result is stateless and reusable.
_graph = build_graph()


@router.post("/process-invoice")
async def process_invoice(
    invoice_metadata: str = Form(...),
    pdf_file: UploadFile = File(...),
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
    # Validate metadata.
    try:
        metadata_dict = json.loads(invoice_metadata)
        invoice_input = InvoiceInput(**metadata_dict)
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid invoice_metadata: {exc}") from exc

    # Read PDF bytes.
    pdf_bytes = await pdf_file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=422, detail="pdf_file is empty")

    invoice_id = str(uuid.uuid4())

    initial_state = {
        "invoice_id": invoice_id,
        "raw_pdf_bytes": pdf_bytes,
        "gmail_message_id": invoice_input.gmail_message_id,
        "parsed_invoice": None,
        "gate_results": [],
        "current_gate": None,
        "gate_failed": False,
        "gate_failure_reason": None,
        "risk_score": None,
        "routing_decision": None,
        "slack_message_ts": None,
        "human_decision": None,
        "audit_record_id": None,
        "error": None,
        "created_at": now_eat(),
    }

    result = await _graph.ainvoke(initial_state)

    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])

    return {
        "invoice_id": result.get("invoice_id"),
        "routing_decision": result.get("routing_decision"),
        "risk_score": result.get("risk_score"),
        "gate_results": result.get("gate_results", []),
        "slack_message_ts": result.get("slack_message_ts"),
    }
