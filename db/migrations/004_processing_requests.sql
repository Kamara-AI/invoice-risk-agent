-- =============================================================================
-- Migration 004: processing_requests  (UiPath contract v1 — idempotency ledger)
--
-- Why this table exists:
--   The UiPath Performer retries a queue item when the Kagua call times out.
--   Without a ledger, the retry re-runs the graph and the duplicate gate sees
--   the invoice number it saved on the first attempt -> a clean invoice gets
--   blocked as fraud. One row per idempotency_key lets Kagua return the stored
--   result (replayed=true) instead.
--
-- Why a NEW table instead of columns on invoice_history:
--   invoice_history is shared with the live Streamlit demo. Adding a table is
--   purely additive: no existing query, constraint or row changes.
--
-- Lifecycle of a row:
--   insert status='processing'  (reservation, before the graph runs)
--   -> update status='completed' + response (after the graph succeeds)
--   -> delete                     (if the graph fails, so the retry can score)
--   review_* columns are filled once by POST /invoices/{id}/review-decision.
--
-- Depends on: 002_invoice_history.sql (invoice_id FK).
-- Safe to re-run (IF NOT EXISTS everywhere).
-- =============================================================================

CREATE TABLE IF NOT EXISTS processing_requests (
    -- Built by the UiPath Dispatcher: 'INV-<hash>-<n>'. Also the queue Reference.
    idempotency_key   TEXT        PRIMARY KEY
                      CHECK (char_length(idempotency_key) <= 128),
    -- SHA-256 of the PDF bytes. Same key + different hash = Dispatcher bug -> 409.
    pdf_sha256        TEXT        NOT NULL CHECK (char_length(pdf_sha256) = 64),
    status            TEXT        NOT NULL DEFAULT 'processing'
                      CHECK (status IN ('processing', 'completed')),
    -- Email Message-ID header, for tracing back to the source email.
    source_message_id TEXT,
    -- Filled on completion. Nullable FK: no invoice_history row exists while processing.
    invoice_id        UUID        REFERENCES invoice_history (invoice_id) ON DELETE SET NULL,
    -- The exact flat contract response returned the first time; replayed verbatim.
    response          JSONB,
    -- Human review outcome from UiPath Action Center (D13). Set once.
    review_decision   TEXT        CHECK (review_decision IN ('approve', 'reject')),
    reviewed_by       TEXT,
    reviewed_at       TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Touched on every state change; used to detect stale 'processing' reservations.
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Review-decision looks rows up by invoice_id as a consistency check.
CREATE INDEX IF NOT EXISTS idx_processing_requests_invoice_id
    ON processing_requests (invoice_id);

-- Row Level Security ON with no policies: only the service-role key (which
-- Kagua uses and which bypasses RLS) can read or write. The anon key, which
-- could be exposed in a browser, gets nothing. Contains no invoice contents,
-- but keys and decisions are still operational data.
ALTER TABLE processing_requests ENABLE ROW LEVEL SECURITY;
