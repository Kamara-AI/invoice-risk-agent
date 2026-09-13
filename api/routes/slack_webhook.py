"""Slack interactive actions webhook route.

POST /slack/action

Receives interactive button payloads from Slack when a reviewer clicks
Approve or Reject on a review card. Verifies the Slack signing secret,
extracts the reviewer decision, and writes it back to the invoice record.

Security: ALL incoming requests must pass Slack signature verification
before any business logic executes. Never skip this step.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.parse

from fastapi import APIRouter, HTTPException, Request

from config import settings
from db.queries import update_invoice_status, write_audit_log
from schemas.audit import AuditRecord
from utils import now_eat

router = APIRouter()

# Slack requires responses within 3 seconds — keep the handler lean.
_MAX_SLACK_TIMESTAMP_SKEW_SECONDS = 300  # 5 minutes


def _verify_slack_signature(
    body: bytes,
    timestamp: str,
    signature: str,
) -> bool:
    """Verify a Slack request signature using the signing secret.

    Slack signs requests with HMAC-SHA256 using the signing secret and a
    composite string of version + timestamp + body. Reject requests older
    than 5 minutes to prevent replay attacks.

    Args:
        body: Raw request body bytes.
        timestamp: Value of the X-Slack-Request-Timestamp header.
        signature: Value of the X-Slack-Signature header.

    Returns:
        True if the signature is valid and the timestamp is fresh, else False.
    """
    try:
        ts = int(timestamp)
    except ValueError:
        return False

    if abs(time.time() - ts) > _MAX_SLACK_TIMESTAMP_SKEW_SECONDS:
        return False

    sig_base = f"v0:{timestamp}:{body.decode('utf-8')}"
    computed = (
        "v0="
        + hmac.new(
            settings.slack_signing_secret.encode("utf-8"),
            sig_base.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
    )
    return hmac.compare_digest(computed, signature)


@router.post("/action")
async def slack_action(request: Request) -> dict:
    """Handle an interactive button action from a Slack review card.

    Verifies the request signature using SLACK_SIGNING_SECRET, then:
    - Extracts invoice_id and decision ('approve' | 'reject') from the payload.
    - Updates invoice_history.status and resolved_by in Supabase.
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
    body = await request.body()

    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    if not _verify_slack_signature(body, timestamp, signature):
        raise HTTPException(status_code=403, detail="Invalid Slack signature")

    # Slack sends interactive payloads as URL-encoded form: payload=<JSON>
    try:
        form_data = urllib.parse.parse_qs(body.decode("utf-8"))
        payload_str = form_data.get("payload", [None])[0]
        if not payload_str:
            raise ValueError("No payload field in form data")
        payload = json.loads(payload_str)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Malformed Slack payload: {exc}") from exc

    try:
        # Extract action details.
        actions = payload.get("actions", [])
        if not actions:
            return {}

        action = actions[0]
        action_id: str = action.get("action_id", "")
        invoice_id: str = action.get("value", "")
        user_id: str = payload.get("user", {}).get("id", "unknown")

        # Determine decision from action_id prefix.
        if action_id.startswith("approve_"):
            decision = "approve"
            new_status = "approved"
        elif action_id.startswith("reject_"):
            decision = "reject"
            new_status = "rejected"
        else:
            # Unknown action — acknowledge without error to avoid Slack retries.
            return {}

        if not invoice_id:
            return {}

        # Persist the human decision.
        update_invoice_status(
            invoice_id,
            new_status,
            {
                "resolved_by": user_id,
                "resolved_at": now_eat(),
            },
        )

        write_audit_log(
            AuditRecord(
                invoice_id=invoice_id,
                event_type=f"human.{decision}",
                actor=user_id,
                details={"decision": decision, "action_id": action_id},
                created_at=now_eat(),
            )
        )

    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Slack action processing failed: {exc}") from exc

    return {}
