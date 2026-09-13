"""Slack integration — human review cards and system alerts.

Uses the Slack SDK (slack-sdk) WebClient. The bot token grants permission to
post messages and update them with review outcomes.

Two channels are used:
- SLACK_REVIEW_CHANNEL_ID: interactive review cards for human_review cases.
- SLACK_ALERT_CHANNEL_ID: system alerts for blocks and errors.

Interactive button payloads from reviewers are handled by the
/slack/action route (api/routes/slack_webhook.py).
"""

from __future__ import annotations

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError  # noqa: F401 — re-exported for callers

from config import settings


class SlackClient:
    """Wrapper around the Slack WebClient for invoice review and alerting.

    All methods raise on Slack API errors. Callers should catch SlackApiError
    and set state.error if the failure is within an agent node.
    """

    def __init__(self) -> None:
        """Initialise the Slack WebClient with the bot token from settings."""
        self.client = WebClient(token=settings.slack_bot_token)

    def send_alert(self, channel: str, text: str) -> None:
        """Post a plain-text alert to the specified Slack channel.

        Used for system errors, OFAC hits, and auto-block notifications.

        Args:
            channel: Slack channel ID to post to.
            text: Alert message text (plain text, no Block Kit).

        Raises:
            slack_sdk.errors.SlackApiError: On API failures.
        """
        self.client.chat_postMessage(channel=channel, text=text)

    def send_review_request(
        self,
        invoice_id: str,
        risk_score: int,
        reasoning: str,
    ) -> str:
        """Post an interactive Block Kit review card to the review channel.

        The card includes invoice summary, risk score, LLM reasoning, and
        Approve / Reject buttons. The reviewer's button click is handled by
        the /slack/action webhook.

        Args:
            invoice_id: Invoice run ID, included in the button action payload
                        so the webhook handler can route the decision back.
            risk_score: Composite risk score (0–100) displayed on the card.
            reasoning: LLM reasoning text displayed in the card body.

        Returns:
            The Slack message timestamp (ts) string, stored in state so the
            message can be updated when the reviewer responds.

        Raises:
            slack_sdk.errors.SlackApiError: On API failures.
        """
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "Invoice Review Required",
                    "emoji": False,
                },
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Invoice ID:*\n`{invoice_id}`",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Risk Score:*\n{risk_score}/100",
                    },
                ],
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*LLM Reasoning:*\n{reasoning}",
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Approve",
                            "emoji": False,
                        },
                        "style": "primary",
                        "action_id": f"approve_{invoice_id}",
                        "value": invoice_id,
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Reject",
                            "emoji": False,
                        },
                        "style": "danger",
                        "action_id": f"reject_{invoice_id}",
                        "value": invoice_id,
                    },
                ],
            },
        ]

        response = self.client.chat_postMessage(
            channel=settings.slack_review_channel_id,
            text=f"Invoice {invoice_id} requires review (risk score: {risk_score})",
            blocks=blocks,
        )
        return response["ts"]
