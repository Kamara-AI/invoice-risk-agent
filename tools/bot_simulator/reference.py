"""Reference implementations of the UiPath bot's pure-logic components.

These are the executable SPEC for three small XAML Sequences Brian builds in
VB (design D17): BuildIdempotencyKey, CleanEmailBody, MaskEmail. Each
function documents the VB expression it corresponds to, and
tests/test_bot_reference.py pins golden input → output vectors. When the XAML
version produces the same outputs for those vectors, it matches Kagua.

classify_status() is the Performer's status-code → exception-type rule from
the contract, written once so the simulator and the docs cannot drift.
"""

from __future__ import annotations

import hashlib
import re
from typing import Literal

EMAIL_BODY_MAX_CHARS = 4000
KEY_HASH_CHARS = 12  # 48 bits of SHA-256: collision-free at invoice volumes, short enough to read in logs


# ---------------------------------------------------------------------------
# BuildIdempotencyKey.xaml
# ---------------------------------------------------------------------------


def build_idempotency_key(message_id: str, attachment_index: int) -> str:
    """Build the per-PDF key: "INV-" + 12 hex chars of SHA-256(Message-ID) + "-" + index.

    Normalisation: surrounding whitespace and angle brackets are removed first,
    because IMAP libraries disagree on whether "<...>" is part of the header
    value. Case is preserved (Message-IDs are case-sensitive).

    VB (one Assign, needs Imports System.Security.Cryptography and System.Text):
        normalized = messageId.Trim().Trim("<"c, ">"c)
        key = "INV-" + Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(normalized))) _
              .Substring(0, 12).ToLowerInvariant() + "-" + attachmentIndex.ToString()

    Args:
        message_id: The email's Message-ID header.
        attachment_index: 1-based position of the PDF among the email's attachments.

    Returns:
        The key, e.g. "INV-3f1d8a9c0b2e-1". Also the queue item Reference.

    Raises:
        ValueError: On an empty Message-ID or an index below 1.
    """
    normalized = message_id.strip().strip("<>")
    if not normalized:
        raise ValueError("message_id is empty")
    if attachment_index < 1:
        raise ValueError("attachment_index is 1-based")
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:KEY_HASH_CHARS]
    return f"INV-{digest}-{attachment_index}"


# ---------------------------------------------------------------------------
# CleanEmailBody.xaml
# ---------------------------------------------------------------------------

# A line that starts the quoted previous message. Everything from it down is dropped.
_QUOTE_START = re.compile(
    r"^(On .+ wrote:|-{2,}\s*Original Message\s*-{2,}|_{10,}|From: .+ <[^>]+>)\s*$",
    re.IGNORECASE,
)
# The standard signature delimiter ("-- ") and mobile footers.
_SIGNATURE_START = re.compile(r"^(--\s?|Sent from my .+)$", re.IGNORECASE)


def clean_email_body(raw: str) -> str:
    """Reduce an email body to the sender's own new text (D12).

    Rules, applied line by line, in order:
      1. Normalise line endings to "\\n".
      2. Stop at the first quote header ("On ... wrote:", "-----Original Message-----",
         an Outlook "____" separator, or a "From: Name <addr>" line).
      3. Stop at the signature delimiter ("--" / "-- ") or "Sent from my ...".
      4. Drop quoted lines starting with ">".
      5. Strip trailing spaces; collapse runs of blank lines to one.
      6. Trim, then truncate to 4,000 characters.

    VB: a For Each over body.Split(vbLf) with the same three checks, appending to
    a StringBuilder; then Regex.Replace(text, "\\n{3,}", vbLf & vbLf).Trim() and
    Left(text, 4000).
    """
    kept: list[str] = []
    for line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = line.rstrip()
        if _QUOTE_START.match(stripped.strip()) or _SIGNATURE_START.match(stripped.strip()):
            break
        if stripped.lstrip().startswith(">"):
            continue
        kept.append(stripped)
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
    return text[:EMAIL_BODY_MAX_CHARS]


# ---------------------------------------------------------------------------
# MaskEmail.xaml
# ---------------------------------------------------------------------------


def mask_email(email: str) -> str:
    """Mask an address for logs: first character of the local part + "***@" + domain.

    "billing@vendor.co.ke" → "b***@vendor.co.ke". No "@" → "***" (never leak a
    malformed value). The domain stays visible because it identifies the vendor,
    which logs need; the mailbox name does not.

    VB:
        If(email.Contains("@") AndAlso email.IndexOf("@") > 0,
           email.Substring(0, 1) + "***" + email.Substring(email.IndexOf("@")), "***")
    """
    email = email.strip()
    at = email.find("@")
    if at <= 0:
        return "***"
    return f"{email[0]}***{email[at:]}"


# ---------------------------------------------------------------------------
# Performer: HTTP status → exception type (contract v1)
# ---------------------------------------------------------------------------

BotOutcome = Literal["success", "business_rule_exception", "system_exception"]


def classify_status(status_code: int | None) -> BotOutcome:
    """Map a Kagua response to what the Performer must do.

    None means no response at all (timeout at 120 s, connection refused).
    200 → route by routing_decision. 5xx or no response → System Exception
    (the queue retries, up to 3). Any other 4xx (409, 422, 404) → Business Rule
    Exception (no retry, alert) — retrying cannot change the answer.
    """
    if status_code is None or status_code >= 500:
        return "system_exception"
    if status_code == 200:
        return "success"
    return "business_rule_exception"
