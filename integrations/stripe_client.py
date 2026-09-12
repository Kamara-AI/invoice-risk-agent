"""Stripe integration — payment fingerprinting and Radar risk scoring.

Uses the Stripe Python SDK. The primary use case is BEC (Business Email
Compromise) detection: if a known vendor's bank account fingerprint changes
between invoices, the gate_stripe node flags it for human review.

Stripe Radar scores provide a secondary signal for high-value invoices
where the payment method itself may be synthetic or stolen.
"""

from __future__ import annotations

import stripe

from config import settings


class StripeClient:
    """Wrapper around the Stripe SDK for invoice payment validation.

    Initialised with the API key from settings. All methods raise stripe.StripeError
    on API failures — callers are responsible for catching these in gate_stripe.
    """

    def __init__(self) -> None:
        """Configure the Stripe SDK with the secret key from settings."""
        pass

    def get_vendor_fingerprint(self, vendor_email: str) -> str | None:
        """Retrieve the payment fingerprint for a vendor's bank account.

        Looks up the most recent Stripe Customer matching vendor_email and
        returns the fingerprint of their default payment method. Returns None
        if no Stripe customer exists for this vendor (new vendor).

        The fingerprint is a stable hash of the underlying account details —
        it changes if the account number, routing number, or card number changes,
        which is the primary BEC detection signal.

        Args:
            vendor_email: The vendor's email address used to look up their Stripe customer.

        Returns:
            The payment fingerprint string, or None if no customer record exists.

        Raises:
            stripe.StripeError: On API failures.
        """
        pass

    def get_radar_score(self, amount: float, vendor_email: str) -> float:
        """Retrieve the Stripe Radar risk score for a prospective payment.

        Creates a Stripe PaymentIntent in 'manual' capture mode (never auto-captured)
        to obtain the Radar risk evaluation. The PaymentIntent is immediately
        cancelled after the score is read — no funds are moved.

        Args:
            amount: Invoice total in the invoice currency (as a float).
            vendor_email: Vendor email, used to attach the PaymentIntent to a customer.

        Returns:
            Radar risk score as a float (0.0–100.0). Higher is riskier.

        Raises:
            stripe.StripeError: On API failures.
        """
        pass
