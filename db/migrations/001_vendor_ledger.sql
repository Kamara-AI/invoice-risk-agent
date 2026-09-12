-- =============================================================================
-- Migration 001: vendor_ledger
-- Tracks every unique vendor the agent has seen. Acts as the long-term memory
-- for vendor trust scoring — a vendor's history across many invoices informs
-- the LLM scoring node and the gate_duplicate check.
-- Run order: must execute before 002_invoice_history.sql (FK dependency).
-- =============================================================================

CREATE TABLE IF NOT EXISTS vendor_ledger (
    vendor_id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name              TEXT        NOT NULL,
    email             TEXT,
    -- Stripe payment fingerprint: stable identifier for a bank account/card,
    -- survives minor detail changes. Used to detect BEC account-swap fraud.
    stripe_fingerprint TEXT,
    -- Stripe Radar risk score for the most recent transaction (0.00–100.00).
    radar_score       NUMERIC(5, 2),
    -- OFAC sanctions screening status. 'unchecked' on first insert;
    -- updated to 'clear' or 'flagged' after gate_ofac runs.
    ofac_status       TEXT        NOT NULL DEFAULT 'unchecked'
                      CHECK (ofac_status IN ('clear', 'flagged', 'unchecked')),
    first_seen        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- trust_level is updated by the route node after each invoice is resolved.
    -- 'trusted' vendors get a lower prior risk score in the LLM prompt.
    trust_level       TEXT        NOT NULL DEFAULT 'new'
                      CHECK (trust_level IN ('new', 'trusted', 'flagged', 'blocked')),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index on name for fast lookup during gate_duplicate (vendor name matching).
CREATE INDEX IF NOT EXISTS idx_vendor_name  ON vendor_ledger (name);

-- Index on email for fast lookup during gate_quality (sender vs invoice email).
CREATE INDEX IF NOT EXISTS idx_vendor_email ON vendor_ledger (email);
