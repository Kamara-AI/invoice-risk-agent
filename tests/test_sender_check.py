"""Tests for agent/sender_check.py — the tiered sender-vs-vendor policy (pure, no I/O).

Run with:
    pytest tests/test_sender_check.py -v
"""

from __future__ import annotations

import pytest

from agent.sender_check import classify_sender


@pytest.mark.parametrize(
    ("sender", "vendor", "expected"),
    [
        # match: same address (case, brackets, spaces ignored) or same company domain
        ("billing@apexoffice.com", "billing@apexoffice.com", "match"),
        (" <Billing@ApexOffice.com> ", "billing@apexoffice.com", "match"),
        ("accounts@apexoffice.com", "billing@apexoffice.com", "match"),
        ("billing@mail.apexoffice.com", "billing@apexoffice.com", "match"),
        ("vendor.ke@gmail.com", "vendor.ke@gmail.com", "match"),
        # lookalike: 1-2 characters off the vendor's company domain → BEC
        ("billing@apex0ffice.com", "billing@apexoffice.com", "lookalike"),
        ("billing@apexofice.com", "billing@apexoffice.com", "lookalike"),
        ("billing@apexoffice.co", "billing@apexoffice.com", "lookalike"),
        ("finance@savasupp1y.co.ke", "finance@savasupply.co.ke", "lookalike"),
        # mismatch: unrelated domain, free mail, accounting platforms → human review
        ("apex.billing@gmail.com", "billing@apexoffice.com", "mismatch"),
        ("someone.else@gmail.com", "vendor.ke@gmail.com", "mismatch"),
        ("billing@apexoffice.com", "apex.billing@gmail.com", "mismatch"),
        ("messaging-service@post.xero.com", "billing@apexoffice.com", "mismatch"),
        ("billing@totallydifferent.org", "billing@apexoffice.com", "mismatch"),
        # a lookalike of a FREE-MAIL domain says nothing about the vendor
        ("vendor@gmial.com", "vendor@gmail.com", "mismatch"),
        # a parent-domain trick is not a subdomain: apexoffice.com.evil.io
        ("billing@apexoffice.com.evil.io", "billing@apexoffice.com", "mismatch"),
    ],
)
def test_classify_sender(sender: str, vendor: str, expected: str) -> None:
    assert classify_sender(sender, vendor) == expected


def test_short_domains_are_not_called_lookalikes() -> None:
    """Below LOOKALIKE_MIN_LENGTH every short domain is 'close' to every other."""
    assert classify_sender("a@ab.io", "b@ac.io") == "mismatch"
