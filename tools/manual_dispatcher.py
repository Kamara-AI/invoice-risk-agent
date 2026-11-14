"""Manual dispatcher — queue invoice PDFs for the UiPath Performer without Gmail.

Does exactly what TechByYou_InvoiceDispatcher will do per PDF (design v2,
"Dispatcher" → "Steps per run"), using the `uip` CLI:

    1. build idempotency_key           (same function the simulator uses)
    2. upload PDF  → TBY-Invoices: incoming/<key>.pdf
    3. upload body → TBY-Invoices: incoming/<key>.txt   (cleaned, D12)
    4. add queue item to TBY_InvoiceQueue, Reference = key, SpecificContent per spec

Order matters: files first, queue item last, so the Performer can never pick
up an item whose PDF is not in the bucket yet. A re-run with the same
Message-ID is safe: the queue's unique-reference rule rejects the repeat and
this script reports it as skipped, exactly like the real Dispatcher.

Why it exists: the design's fallback "if the week runs short, invoices can be
added to the queue by hand and still get scored and filed" — this is that hand,
made repeatable. It lets the Performer be built and demoed before Gmail is set up.

Usage (repo root; needs `uip login` first):
    python -m tools.manual_dispatcher --demo                 # queue the 3-route demo set
    python -m tools.manual_dispatcher --demo --dry-run       # print the plan, touch nothing
    python -m tools.manual_dispatcher --pdf path/to/inv.pdf --sender billing@vendor.co.ke \
        --subject "Invoice 4471" [--body-file email.txt]
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from tools.bot_simulator.reference import build_idempotency_key, clean_email_body, mask_email
from utils import EAT

FOLDER = "TechByYou"
BUCKET = "TBY-Invoices"
QUEUE = "TBY_InvoiceQueue"
FIXTURES = Path(__file__).resolve().parent.parent / "evals" / "fixtures"


@dataclass(frozen=True)
class InvoiceJob:
    """One PDF to dispatch, as it would arrive by email."""

    pdf_path: Path
    sender_email: str
    subject: str
    email_body: str
    message_id: str
    attachment_index: int = 1
    expected_routing: str | None = None  # demo set only — for the presenter, not sent anywhere


@dataclass(frozen=True)
class DispatchPlan:
    """Everything the four steps need, computed up front (pure, testable)."""

    idempotency_key: str
    pdf_bucket_path: str
    body_bucket_path: str
    specific_content: dict[str, str]


# Demo set: one invoice per route, chosen so the outcome does not depend on
# what is already in the database (the block is a deterministic math-gate fail).
DEMO_SET: list[tuple[str, str, str, str]] = [
    ("clean_001.pdf", "auto_approve", "Invoice for October services", "Hi, please find our October invoice attached. Regards, Accounts"),
    ("edge_001.pdf", "human_review", "Overdue invoice - first time supplier", "Hello, this is our first invoice to you. Kindly process at your earliest. Thanks"),
    ("fraud_math_001.pdf", "block", "Invoice attached", "Please pay the attached invoice today."),
]


def build_plan(job: InvoiceJob, received_at: datetime) -> DispatchPlan:
    """Compute key, bucket paths and SpecificContent for one PDF (no I/O)."""
    key = build_idempotency_key(job.message_id, job.attachment_index)
    pdf_bucket_path = f"incoming/{key}.pdf"
    return DispatchPlan(
        idempotency_key=key,
        pdf_bucket_path=pdf_bucket_path,
        body_bucket_path=f"incoming/{key}.txt",
        # Exactly the seven keys in design v2 "Queue item SpecificContent".
        # The email body is NOT here: it lives only in the bucket (D12).
        specific_content={
            "idempotency_key": key,
            "source_message_id": job.message_id,
            "sender_email": job.sender_email,
            "subject": job.subject,
            "received_at": received_at.astimezone(EAT).isoformat(timespec="seconds"),
            "pdf_filename": job.pdf_path.name,
            "bucket_path": pdf_bucket_path,
        },
    )


class UipError(RuntimeError):
    """A `uip` command returned a non-Success result."""


class UipCli:
    """Thin wrapper over the `uip` CLI: one method per command, JSON in/out.

    The CLI (not hand-rolled REST) owns auth, folder headers and retries.
    """

    def __init__(self) -> None:
        exe = shutil.which("uip")
        if exe is None:
            raise UipError("`uip` CLI not found on PATH")
        self._exe = exe
        # Robot-auth enforcement would ignore the saved user login; drop it for this process.
        self._env = {k: v for k, v in os.environ.items() if k != "UIPATH_CLI_ENFORCE_ROBOT_AUTH"}

    def _run(self, *args: str) -> dict:
        completed = subprocess.run(
            [self._exe, *args, "--output", "json"],
            capture_output=True, text=True, env=self._env, timeout=180,
        )
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise UipError(f"uip {args[0]} {args[1]}: non-JSON output: {completed.stdout[:300]}") from exc
        if result.get("Result") != "Success":
            raise UipError(f"uip {' '.join(args[:2])}: {result.get('Message')} — {result.get('Instructions', '')}")
        return result

    def check_login(self) -> str:
        data = self._run("login", "status")["Data"]
        if data.get("Status") != "Logged in":
            raise UipError(f"not logged in ({data.get('Status')}): run `uip login`")
        return f"{data.get('Organization')}/{data.get('Tenant')}"

    def bucket_key(self, folder: str, name: str) -> str:
        buckets = self._run("or", "buckets", "list", "--folder-path", folder, "--name", name)["Data"]
        for bucket in buckets:
            if bucket["Name"] == name:
                return bucket["Identifier"]
        raise UipError(f"bucket {name!r} not found in folder {folder!r}")

    def upload(self, bucket_key: str, folder: str, bucket_path: str, local_file: Path, content_type: str) -> None:
        self._run("or", "bucket-files", "upload", bucket_key, bucket_path, "--folder-path", folder,
                  "--file", str(local_file), "--content-type", content_type)

    def add_queue_item(self, queue: str, folder: str, specific_content: dict[str, str], reference: str) -> str:
        data = self._run("or", "queue-items", "add", queue, "--folder-path", folder,
                         "--specific-content", json.dumps(specific_content), "--reference", reference)["Data"]
        return str(data.get("Key") or data.get("Id") or "")


def _is_duplicate_reference(error: UipError) -> bool:
    text = str(error).lower()
    return "unique" in text or "duplicate" in text or "already exists" in text


def dispatch(jobs: list[InvoiceJob], cli: UipCli | None, dry_run: bool) -> dict:
    """Run the four steps for each job and return a JSON-serialisable summary.

    Log hygiene: the summary carries keys, masked senders and paths — never
    email bodies or invoice contents.
    """
    summary: dict = {"dry_run": dry_run, "queued": [], "skipped_duplicates": [], "errors": []}
    if not dry_run:
        assert cli is not None
        summary["tenant"] = cli.check_login()
        bucket_key = cli.bucket_key(FOLDER, BUCKET)

    for job in jobs:
        plan = build_plan(job, datetime.now(EAT))
        entry = {
            "idempotency_key": plan.idempotency_key,
            "pdf": job.pdf_path.name,
            "sender": mask_email(job.sender_email),
            "bucket_path": plan.pdf_bucket_path,
            "expected_routing": job.expected_routing,
        }
        if dry_run:
            summary["queued"].append(entry | {"specific_content_keys": sorted(plan.specific_content)})
            continue
        try:
            with tempfile.TemporaryDirectory() as tmp:
                body_file = Path(tmp) / f"{plan.idempotency_key}.txt"
                body_file.write_text(clean_email_body(job.email_body), encoding="utf-8")
                cli.upload(bucket_key, FOLDER, plan.pdf_bucket_path, job.pdf_path, "application/pdf")
                cli.upload(bucket_key, FOLDER, plan.body_bucket_path, body_file, "text/plain")
            entry["queue_item_key"] = cli.add_queue_item(QUEUE, FOLDER, plan.specific_content, plan.idempotency_key)
            summary["queued"].append(entry)
        except UipError as exc:
            if _is_duplicate_reference(exc):
                summary["skipped_duplicates"].append(entry)
            else:
                summary["errors"].append(entry | {"error": str(exc)[:300]})
    return summary


def demo_jobs(run_id: str) -> list[InvoiceJob]:
    """The 3-route demo set with fresh Message-IDs, so every demo run queues new items."""
    return [
        InvoiceJob(
            pdf_path=FIXTURES / filename,
            sender_email="billing@demo-vendor.co.ke",
            subject=subject,
            email_body=body,
            message_id=f"<demo-{run_id}-{filename.removesuffix('.pdf')}@kagua.local>",
            expected_routing=expected,
        )
        for filename, expected, subject, body in DEMO_SET
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Queue invoice PDFs for the UiPath Performer (no Gmail).")
    parser.add_argument("--demo", action="store_true", help="Queue the 3-route demo set.")
    parser.add_argument("--pdf", type=Path, help="A single PDF to queue.")
    parser.add_argument("--sender", default="billing@vendor.co.ke")
    parser.add_argument("--subject", default="Invoice")
    parser.add_argument("--body-file", type=Path, help="Raw email body text file (cleaned before upload).")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan; touch nothing.")
    args = parser.parse_args(argv)

    run_id = datetime.now(EAT).strftime("%Y%m%d%H%M%S") + secrets.token_hex(2)
    if args.demo:
        jobs = demo_jobs(run_id)
    elif args.pdf:
        if not args.pdf.read_bytes().startswith(b"%PDF"):
            parser.error(f"{args.pdf} is not a PDF")
        body = args.body_file.read_text(encoding="utf-8") if args.body_file else ""
        jobs = [InvoiceJob(args.pdf, args.sender, args.subject, body, f"<manual-{run_id}@kagua.local>")]
    else:
        parser.error("pass --demo or --pdf")

    try:
        summary = dispatch(jobs, None if args.dry_run else UipCli(), args.dry_run)
    except UipError as exc:
        print(json.dumps({"error": str(exc)}, indent=2))
        return 2
    print(json.dumps(summary, indent=2))
    return 0 if not summary["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
