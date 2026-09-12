-- =============================================================================
-- Migration 002: invoice_history
-- One row per processed invoice. This is the primary operational record:
-- it is created at ingest and updated as the invoice moves through the pipeline.
-- Depends on: 001_vendor_ledger.sql (vendor_id FK).
-- =============================================================================

CREATE TABLE IF NOT EXISTS invoice_history (
    invoice_id        UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    -- FK to vendor_ledger; allows vendor-level aggregation (total billed, frequency, etc.)
    vendor_id         UUID        REFERENCES vendor_ledger (vendor_id) ON DELETE SET NULL,
    invoice_number    TEXT        NOT NULL,
    amount            NUMERIC     NOT NULL CHECK (amount >= 0),
    currency          TEXT        NOT NULL DEFAULT 'USD',
    submitted_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Full ordered list of gate outcomes as JSONB (list of GateResult dicts).
    gate_results      JSONB,
    -- Composite risk score produced by the LLM scoring node (0–100).
    risk_score        INT         CHECK (risk_score BETWEEN 0 AND 100),
    -- List of risk flag strings from the LLM (e.g. ["math_mismatch", "ofac_hit"]).
    risk_flags        JSONB,
    routing_decision  TEXT        CHECK (routing_decision IN ('auto_approve', 'human_review', 'block')),
    -- Slack user ID of the human reviewer, or 'system' for automated decisions.
    resolved_by       TEXT,
    resolved_at       TIMESTAMPTZ,
    -- Current lifecycle status of this invoice record.
    status            TEXT        NOT NULL DEFAULT 'processing'
                      CHECK (status IN ('processing', 'approved', 'rejected', 'blocked', 'error')),
    -- Cross-reference back to Gmail for re-fetching or labelling the source message.
    gmail_message_id  TEXT,
    -- Slack message timestamp for updating the review card when a decision is made.
    slack_message_ts  TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Partial index: fast lookup of all invoices currently awaiting human review.
CREATE INDEX IF NOT EXISTS idx_invoice_status
    ON invoice_history (status)
    WHERE status IN ('processing', 'approved', 'rejected', 'blocked');

-- Index to support vendor-level history queries in gate_duplicate.
CREATE INDEX IF NOT EXISTS idx_invoice_vendor
    ON invoice_history (vendor_id);
