"""Tests for tools/manual_dispatcher.py with a fake `uip` CLI.

Proves the Dispatcher contract without touching Orchestrator: SpecificContent
has exactly the seven spec keys, files are uploaded before the queue item,
the email body never enters the queue item, and duplicate references are
reported as skipped (re-runs are safe).

Run with:
    pytest tests/test_manual_dispatcher.py -v
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from tools import manual_dispatcher as md
from tools.bot_simulator.reference import build_idempotency_key
from utils import EAT

SPEC_KEYS = {"idempotency_key", "source_message_id", "sender_email", "subject",
             "received_at", "pdf_filename", "bucket_path"}


class FakeCli:
    """Records calls in order; optionally rejects a reference as duplicate."""

    def __init__(self, duplicate_refs: set[str] | None = None) -> None:
        self.calls: list[tuple] = []
        self.uploaded_bodies: dict[str, str] = {}
        self.duplicate_refs = duplicate_refs or set()

    def check_login(self) -> str:
        return "kamarauipath/DefaultTenant"

    def bucket_key(self, folder: str, name: str) -> str:
        return "bucket-guid"

    def upload(self, bucket_key, folder, bucket_path, local_file: Path, content_type) -> None:
        self.calls.append(("upload", bucket_path, content_type))
        if content_type == "text/plain":
            self.uploaded_bodies[bucket_path] = local_file.read_text(encoding="utf-8")

    def add_queue_item(self, queue, folder, specific_content, reference) -> str:
        if reference in self.duplicate_refs:
            raise md.UipError("Error creating queue item: Error: Duplicate reference. Unique reference is enforced")
        self.calls.append(("queue", queue, reference, dict(specific_content)))
        return "item-key"


def _job(**overrides) -> md.InvoiceJob:
    data = dict(pdf_path=md.FIXTURES / "clean_001.pdf", sender_email="billing@vendor.co.ke",
                subject="Invoice 4471", email_body="Pay please.\n-- \nSig\n> quoted",
                message_id="<CAF=abc123@mail.gmail.com>")
    data.update(overrides)
    return md.InvoiceJob(**data)


def test_plan_matches_design_spec() -> None:
    plan = md.build_plan(_job(), datetime(2026, 11, 14, 9, 14, tzinfo=EAT))

    assert plan.idempotency_key == "INV-1b907f8969aa-1"  # golden vector
    assert set(plan.specific_content) == SPEC_KEYS
    assert plan.specific_content["bucket_path"] == "incoming/INV-1b907f8969aa-1.pdf"
    assert plan.specific_content["received_at"] == "2026-11-14T09:14:00+03:00"
    assert plan.body_bucket_path == "incoming/INV-1b907f8969aa-1.txt"


def test_files_uploaded_before_queue_item_and_body_cleaned() -> None:
    cli = FakeCli()
    summary = md.dispatch([_job()], cli, dry_run=False)

    assert [c[0] for c in cli.calls] == ["upload", "upload", "queue"]
    assert cli.calls[0][1].endswith(".pdf") and cli.calls[1][1].endswith(".txt")
    assert cli.uploaded_bodies["incoming/INV-1b907f8969aa-1.txt"] == "Pay please."
    queued_content = cli.calls[2][3]
    assert "Pay please" not in str(queued_content), "email body must never enter the queue item (D12)"
    assert summary["queued"][0]["sender"] == "b***@vendor.co.ke"
    assert summary["errors"] == []


def test_duplicate_reference_is_skipped_not_error() -> None:
    key = build_idempotency_key("<CAF=abc123@mail.gmail.com>", 1)
    summary = md.dispatch([_job()], FakeCli(duplicate_refs={key}), dry_run=False)

    assert summary["queued"] == []
    assert summary["skipped_duplicates"][0]["idempotency_key"] == key
    assert summary["errors"] == []


def test_dry_run_touches_nothing() -> None:
    summary = md.dispatch(md.demo_jobs("run1"), cli=None, dry_run=True)

    assert summary["dry_run"] is True
    assert [q["expected_routing"] for q in summary["queued"]] == ["auto_approve", "human_review", "block"]
    assert all(set(q["specific_content_keys"]) == SPEC_KEYS for q in summary["queued"])


def test_demo_runs_get_fresh_keys() -> None:
    first = {j.message_id for j in md.demo_jobs("run1")}
    second = {j.message_id for j in md.demo_jobs("run2")}
    assert first.isdisjoint(second), "each demo run must queue new items, not collide with the last run"


def test_demo_fixtures_exist_and_are_pdfs() -> None:
    for job in md.demo_jobs("x"):
        assert job.pdf_path.read_bytes().startswith(b"%PDF"), job.pdf_path
