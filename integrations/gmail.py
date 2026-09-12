"""Gmail integration — invoice ingestion and message labelling.

Uses the Google Gmail API (v1) with OAuth2 refresh-token flow. The client
is designed to be instantiated once per request — no connection pooling is
needed because the Google client library manages HTTP sessions internally.

Credentials are sourced from config.settings; never hardcode them here.
"""

from __future__ import annotations

from config import settings


class GmailClient:
    """Thin wrapper around the Gmail API for invoice ingestion.

    Authenticates via OAuth2 using the refresh token stored in settings.
    All methods raise on API errors — callers (agent nodes) are responsible
    for catching and setting state.error.
    """

    def __init__(self) -> None:
        """Initialise the Gmail API service client using stored OAuth2 credentials."""
        pass

    def fetch_invoice(self, message_id: str) -> tuple[dict, bytes]:
        """Fetch a Gmail message and extract its PDF attachment.

        Args:
            message_id: The Gmail message ID to retrieve.

        Returns:
            A tuple of (message_metadata dict, pdf_bytes). The metadata dict
            includes sender, subject, and received_at for InvoiceInput construction.

        Raises:
            ValueError: If the message has no PDF attachment.
            googleapiclient.errors.HttpError: On API failures.
        """
        pass

    def label_message(self, message_id: str, label: str) -> None:
        """Apply a Gmail label to a processed message.

        Used to mark invoices as 'processed', 'flagged', or 'blocked' so the
        inbox stays clean and avoids re-processing on the next poll cycle.

        Args:
            message_id: The Gmail message ID to label.
            label: The label name to apply (will be created if it does not exist).

        Raises:
            googleapiclient.errors.HttpError: On API failures.
        """
        pass
