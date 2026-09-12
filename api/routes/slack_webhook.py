"""Slack interactive actions webhook route.

POST /slack/action

Receives interactive button payloads from Slack when a reviewer clicks
Approve or Reject on a review card. Verifies the Slack signing secret,
extracts the reviewer decision, and writes it back to the invoice record.

Security: ALL incoming requests must pass Slack signature verification
before any business logic executes. Never skip this step.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from config import settings

router = APIRouter()


@router.post("/action")
async def slack_action(request: Request) -> dict:
    """Handle an interactive button action from a Slack review card.

    Verifies the request signature using SLACK_SIGNING_SECRET, then:
    - Extracts invoice_id and decision ('approve' | 'reject') from the payload.
    - Updates invoice_history.status and resolved_by in Supabase.
    - Updates the Slack review card to reflect the decision.
    - Writes an audit log entry with the reviewer's Slack user ID as actor.

    Args:
        request: The raw FastAPI Request object. Body is read as form-encoded
                 payload per Slack's interactive component specification.

    Returns:
        An empty dict (HTTP 200) to acknowledge the action to Slack.
        Slack requires a 200 response within 3 seconds.

    Raises:
        HTTPException 403: If the Slack signature verification fails.
        HTTPException 500: On unexpected processing errors.
    """
    pass
