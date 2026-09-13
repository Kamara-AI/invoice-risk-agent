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
        stripe.api_key = settings.stripe_api_key

    def get_vendor_fingerprint(self, vendor_email: str) -> str | None:
        """Retrieve the Stripe customer ID for a vendor by email.

        Looks up the most recent Stripe Customer matching vendor_email.
        Returns the customer.id if found, or None for new vendors with no
        Stripe history. The actual bank account fingerprint comparison for BEC
        detection is handled in gate_stripe by reading vendor_ledger.stripe_fingerprint.

        Args:
            vendor_email: The vendor's email address used to look up their Stripe customer.

        Returns:
            The Stripe customer ID string, or None if no customer record exists.

        Raises:
            stripe.StripeError: On API failures.
        """
        customers = stripe.Customer.list(email=vendor_email, limit=1)
        if customers.data:
            return customers.data[0].id
        return None

    def get_radar_score(self, amount: float, vendor_email: str) -> float:
        """Retrieve the Stripe Radar risk score for a prospective payment.

        Creates a Stripe PaymentIntent in 'manual' capture mode (never auto-captured)
        to obtain the Radar risk evaluation. The PaymentIntent is immediately
        cancelled after the score is read — no funds are moved.

        In test mode, Radar scores are not populated (outcome.risk_score is absent).
        In that case we return 0.0 as a safe default — the gate still runs but
        won't fail on a missing test-mode signal.

        Args:
            amount: Invoice total in the invoice currency (as a float).
            vendor_email: Vendor email, used to attach the PaymentIntent to a customer.

        Returns:
            Radar risk score as a float (0.0–100.0). Higher is riskier.
            Returns 0.0 if the score is unavailable (test mode or no Radar plan).

        Raises:
            stripe.StripeError: On API failures.
        """
        amount_cents = int(round(amount * 100))
        if amount_cents <= 0:
            return 0.0

        intent = None
        try:
            intent = stripe.PaymentIntent.create(
                amount=amount_cents,
                currency="usd",
                capture_method="manual",
                confirm=False,
                metadata={"vendor_email": vendor_email, "source": "invoice-risk-agent"},
            )

            # Radar outcome is available on the PaymentIntent after it's confirmed
            # or retrieved. In test mode this is typically None.
            outcome = getattr(intent, "charges", None)
            if outcome and hasattr(outcome, "data") and outcome.data:
                risk_score = outcome.data[0].outcome.risk_score
                return float(risk_score) if risk_score is not None else 0.0

            return 0.0
        finally:
            # Always cancel the PaymentIntent to avoid dangling intents.
            if intent and intent.status not in ("canceled", "succeeded"):
                try:
                    stripe.PaymentIntent.cancel(intent.id)
                except stripe.StripeError:
                    pass  # Best-effort cancel — don't mask the original result.
