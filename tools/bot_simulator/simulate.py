"""Scenario runner: plays the UiPath bot against a running Kagua and checks contract v1.

Each scenario sends exactly what the Dispatcher/Performer/Review Handler will
send (keys from build_idempotency_key, bodies from clean_email_body) and checks
the status code, the error_code, the body schema, and the Performer's outcome
(classify_status). Output is one JSON report on stdout — predictable enough to
feed n8n or a CI step — and the exit code is 0 only if every scenario passed.

Offline scenarios touch neither the database nor the LLM, so they are safe to
run anytime. Live scenarios score real PDFs: they write rows to Supabase, cost
a few cents of OpenAI, and may post to Slack — run them deliberately.

Every run uses fresh synthetic Message-IDs (run_id in the id), so re-running
never replays an earlier run's results.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import httpx
from pydantic import ValidationError

from schemas.contract import ProcessInvoiceResponse, ReviewDecisionResponse
from tools.bot_simulator.invoice_factory import (
    InvoiceSpec,
    fresh_clean_invoice,
    fresh_review_invoice,
    render_invoice_pdf,
)
from tools.bot_simulator.pdf_factory import NEWSLETTER_LINES, make_text_pdf
from tools.bot_simulator.reference import build_idempotency_key, classify_status, clean_email_body
from utils import EAT

REQUEST_TIMEOUT_SECONDS = 120.0  # same as asset TBY_KaguaTimeoutMs
DEFAULT_FIXTURES = Path(__file__).resolve().parents[2] / "evals" / "fixtures"
UNKNOWN_INVOICE_ID = "00000000-0000-0000-0000-000000000000"

# A realistic raw email body; the bot sends it through clean_email_body first.
RAW_EMAIL_BODY = (
    "Hi,\r\n\r\nPlease find attached our invoice for October.\r\n\r\nRegards,\r\nAccounts\r\n"
    "-- \r\nAcme Ltd | Nairobi\r\n\r\nOn Mon, 10 Nov 2026 at 09:00, Brian <brian@example.com> wrote:\r\n"
    "> Please send the invoice.\r\n"
)


@dataclass
class ScenarioResult:
    """One line of the report. `detail` never contains email bodies or invoice contents."""

    scenario: str
    passed: bool
    expected: str
    actual: str
    outcome: str = ""
    detail: str = ""


@dataclass
class RunContext:
    """Shared state for one simulator run."""

    client: httpx.Client
    fixtures: Path
    run_id: str
    scored: dict[str, dict] = field(default_factory=dict)  # scenario name → 200 body

    def message_id(self, label: str) -> str:
        return f"<sim-{self.run_id}-{label}@kagua.test>"

    def metadata(self, label: str, pdf_filename: str, index: int = 1, **overrides) -> dict:
        data = {
            "idempotency_key": build_idempotency_key(self.message_id(label), index),
            "source_message_id": self.message_id(label),
            "sender_email": "billing@acme-sim.co.ke",
            "subject": f"Invoice {label}",
            "received_at": datetime.now(EAT).isoformat(timespec="seconds"),
            "pdf_filename": pdf_filename,
            "email_body": clean_email_body(RAW_EMAIL_BODY),
        }
        data.update(overrides)
        return data

    def post_invoice(self, metadata: dict | str, pdf: bytes | None, filename: str = "invoice.pdf") -> httpx.Response | None:
        """POST like the Performer. Returns None when no response arrived (timeout/refused)."""
        files = {"pdf_file": (filename, pdf, "application/pdf")} if pdf is not None else None
        raw = metadata if isinstance(metadata, str) else json.dumps(metadata)
        try:
            return self.client.post("/invoices/process-invoice", data={"invoice_metadata": raw}, files=files)
        except httpx.TransportError:
            return None

    def post_review(self, invoice_id: str, key: str, decision: str) -> httpx.Response | None:
        body = {"idempotency_key": key, "decision": decision, "reviewer": "simulator",
                "comment": "Simulated review decision.", "decided_at": datetime.now(EAT).isoformat()}
        try:
            return self.client.post(f"/invoices/{invoice_id}/review-decision", json=body)
        except httpx.TransportError:
            return None

    def fixture(self, name: str) -> bytes:
        return (self.fixtures / name).read_bytes()

    def invoice_metadata(self, label: str, spec: InvoiceSpec) -> dict:
        """Metadata for a generated invoice: the sender is the vendor itself, as in real mail."""
        return self.metadata(label, f"{spec.invoice_number}.pdf", sender_email=spec.vendor_email)


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------


def _status(response: httpx.Response | None) -> int | None:
    return None if response is None else response.status_code


def _expect_error(name: str, response: httpx.Response | None, status: int, error_code: str) -> ScenarioResult:
    actual_status = _status(response)
    actual_code = ""
    if response is not None:
        try:
            actual_code = response.json().get("error_code", "")
        except ValueError:
            actual_code = "<non-JSON body>"
    return ScenarioResult(
        scenario=name,
        passed=actual_status == status and actual_code == error_code,
        expected=f"{status} {error_code}",
        actual=f"{actual_status} {actual_code}".strip(),
        outcome=classify_status(actual_status),
    )


def _expect_scored(name: str, response: httpx.Response | None, replayed: bool) -> tuple[ScenarioResult, dict | None]:
    actual_status = _status(response)
    if actual_status != 200:
        detail = response.text[:200] if response is not None else "no response"
        return ScenarioResult(name, False, f"200 replayed={replayed}", str(actual_status),
                              classify_status(actual_status), detail), None
    try:
        body = ProcessInvoiceResponse.model_validate(response.json()).model_dump()
    except (ValueError, ValidationError) as exc:
        return ScenarioResult(name, False, "200 contract body", "200 invalid body", "success", str(exc)[:200]), None
    ok = body["replayed"] is replayed
    return ScenarioResult(
        scenario=name, passed=ok, expected=f"200 replayed={replayed}",
        actual=f"200 replayed={body['replayed']} routing={body['routing_decision']} score={body['risk_score']}",
        outcome="success",
    ), body


# ---------------------------------------------------------------------------
# Offline scenarios — no database, no LLM
# ---------------------------------------------------------------------------


def health_ok(ctx: RunContext) -> list[ScenarioResult]:
    try:
        response = ctx.client.get("/health")
        ok = response.status_code == 200 and response.json() == {"status": "ok"}
        actual = f"{response.status_code} {response.text[:60]}"
    except httpx.TransportError as exc:
        ok, actual = False, f"no response ({type(exc).__name__})"
    return [ScenarioResult("health_ok", ok, '200 {"status": "ok"}', actual)]


def rejects_non_pdf(ctx: RunContext) -> list[ScenarioResult]:
    response = ctx.post_invoice(ctx.metadata("nonpdf", "notes.pdf"), b"<html>not a pdf</html>")
    return [_expect_error("rejects_non_pdf", response, 422, "unreadable_pdf")]


def rejects_malformed_key(ctx: RunContext) -> list[ScenarioResult]:
    response = ctx.post_invoice(ctx.metadata("badkey", "a.pdf", idempotency_key="12345"), make_text_pdf(["x"]))
    return [_expect_error("rejects_malformed_key", response, 422, "invalid_metadata")]


def rejects_v0_metadata(ctx: RunContext) -> list[ScenarioResult]:
    v0 = {"gmail_message_id": "18c2f", "sender_email": "a@b.co", "subject": "s",
          "received_at": "2026-11-14T18:00:00+03:00", "pdf_filename": "a.pdf"}
    response = ctx.post_invoice(v0, make_text_pdf(["x"]))
    return [_expect_error("rejects_v0_metadata", response, 422, "invalid_metadata")]


def rejects_missing_pdf_part(ctx: RunContext) -> list[ScenarioResult]:
    response = ctx.post_invoice(ctx.metadata("nopart", "a.pdf"), None)
    return [_expect_error("rejects_missing_pdf_part", response, 422, "invalid_request")]


# ---------------------------------------------------------------------------
# Live scenarios — database + LLM (+ possibly Slack)
# ---------------------------------------------------------------------------


def _expect_routing(name: str, body: dict | None, expected: str) -> ScenarioResult:
    """Check where Kagua routed a scored invoice. Score + flags go in `detail` for diagnosis."""
    if body is None:
        return ScenarioResult(name, False, expected, "not scored")
    detail = "" if body["routing_decision"] == expected else (
        f"score={body['risk_score']} flags={body.get('risk_flags')}"
    )
    return ScenarioResult(
        scenario=name, passed=body["routing_decision"] == expected, expected=expected,
        actual=f"{body['routing_decision']} score={body['risk_score']}", detail=detail,
    )


def score_replay_conflict(ctx: RunContext) -> list[ScenarioResult]:
    """The core idempotency story: fresh → retry replays → same key + other PDF conflicts.

    Uses a freshly generated invoice (invoice_factory): a static fixture would
    hit gate_duplicate from earlier runs and never reach the scoring path.
    """
    spec = fresh_clean_invoice(ctx.run_id, datetime.now(EAT).date())
    meta = ctx.invoice_metadata("main", spec)
    pdf = render_invoice_pdf(spec)

    fresh, first = _expect_scored("fresh_score", ctx.post_invoice(meta, pdf), replayed=False)
    results = [fresh]
    if first is None:
        return results
    ctx.scored["main"] = first | {"idempotency_key": meta["idempotency_key"]}
    results.append(_expect_routing("clean_invoice_auto_approves", first, "auto_approve"))

    replay, second = _expect_scored("retry_replays_same_result", ctx.post_invoice(meta, pdf), replayed=True)
    if second is not None and {**second, "replayed": False} != first:
        replay.passed, replay.detail = False, "replayed body differs from the first response"
    results.append(replay)

    # Same key, different PDF bytes → Kagua must refuse before scoring anything.
    other_pdf = render_invoice_pdf(fresh_clean_invoice(f"{ctx.run_id}-other", datetime.now(EAT).date()))
    results.append(_expect_error(
        "same_key_different_pdf_conflicts", ctx.post_invoice(meta, other_pdf),
        409, "idempotency_conflict",
    ))
    return results


def score_review_invoice(ctx: RunContext) -> list[ScenarioResult]:
    """A new-vendor invoice with stacked soft signals should route to human_review.

    LLM scoring varies run to run; if it lands elsewhere the result says where
    and why (score + flags), and the review-decision checks are skipped.
    """
    spec = fresh_review_invoice(ctx.run_id, datetime.now(EAT).date())
    meta = ctx.invoice_metadata("review", spec)
    scored, body = _expect_scored("review_invoice_scored", ctx.post_invoice(meta, render_invoice_pdf(spec)),
                                  replayed=False)
    results = [scored, _expect_routing("review_invoice_routes_to_review", body, "human_review")]
    if body is not None:
        ctx.scored["review"] = body | {"idempotency_key": meta["idempotency_key"]}
    return results


def rejects_not_an_invoice(ctx: RunContext) -> list[ScenarioResult]:
    response = ctx.post_invoice(ctx.metadata("newsletter", "newsletter.pdf"), make_text_pdf(NEWSLETTER_LINES))
    return [_expect_error("rejects_not_an_invoice", response, 422, "not_an_invoice")]


def review_decision_flow(ctx: RunContext) -> list[ScenarioResult]:
    """Review rules: only human_review invoices; same decision replays; different decision conflicts."""
    results = [_expect_error(
        "review_unknown_invoice_404",
        ctx.post_review(UNKNOWN_INVOICE_ID, build_idempotency_key(ctx.message_id("ghost"), 1), "approve"),
        404, "invoice_not_found",
    )]
    # A decision on an invoice that was NOT routed to review must be refused.
    main = ctx.scored.get("main")
    if main is not None and main["routing_decision"] != "human_review":
        results.append(_expect_error(
            "review_non_review_invoice_409",
            ctx.post_review(main["invoice_id"], main["idempotency_key"], "approve"),
            409, "decision_conflict",
        ))

    review = ctx.scored.get("review")
    if review is None or review["routing_decision"] != "human_review":
        actual = "not scored" if review is None else review["routing_decision"]
        return results + [ScenarioResult(
            "review_flow", False, "a human_review invoice", actual,
            detail="review invoice did not route to human_review; approve/replay/conflict checks not run",
        )]

    invoice_id, key = review["invoice_id"], review["idempotency_key"]
    first = ctx.post_review(invoice_id, key, "approve")
    again = ctx.post_review(invoice_id, key, "approve")
    for name, response, replayed in (("review_approve", first, False), ("review_approve_again_replays", again, True)):
        try:
            body = ReviewDecisionResponse.model_validate(response.json()) if response is not None else None
            ok = response is not None and response.status_code == 200 and body is not None and body.replayed is replayed
        except (ValueError, ValidationError):
            ok = False
        results.append(ScenarioResult(name, ok, f"200 replayed={replayed}", str(_status(response))))
    results.append(_expect_error("review_conflicting_decision_409", ctx.post_review(invoice_id, key, "reject"),
                                 409, "decision_conflict"))
    return results


OFFLINE_SCENARIOS: list[Callable[[RunContext], list[ScenarioResult]]] = [
    health_ok, rejects_non_pdf, rejects_malformed_key, rejects_v0_metadata, rejects_missing_pdf_part,
]
LIVE_SCENARIOS: list[Callable[[RunContext], list[ScenarioResult]]] = [
    score_replay_conflict, score_review_invoice, rejects_not_an_invoice, review_decision_flow,
]


def run(client: httpx.Client, live: bool, fixtures: Path = DEFAULT_FIXTURES) -> dict:
    """Run the scenario suite and return the JSON-serialisable report."""
    ctx = RunContext(client=client, fixtures=fixtures,
                     run_id=datetime.now(EAT).strftime("%Y%m%d%H%M%S") + secrets.token_hex(2))
    results: list[ScenarioResult] = []
    for scenario in OFFLINE_SCENARIOS + (LIVE_SCENARIOS if live else []):
        results.extend(scenario(ctx))
    passed = sum(r.passed for r in results)
    return {
        "run_id": ctx.run_id,
        "mode": "live" if live else "offline",
        "finished_at": datetime.now(EAT).isoformat(timespec="seconds"),
        "passed": passed,
        "failed": len(results) - passed,
        "results": [asdict(r) for r in results],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--live", action="store_true",
                        help="Also run scoring scenarios (writes DB rows, costs OpenAI, may post Slack).")
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    args = parser.parse_args(argv)

    with httpx.Client(base_url=args.base_url, timeout=REQUEST_TIMEOUT_SECONDS) as client:
        report = run(client, live=args.live, fixtures=args.fixtures)
    print(json.dumps(report, indent=2))
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
