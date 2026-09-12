-- =============================================================================
-- Migration 003: audit_log
-- Append-only event log. Every significant agent action writes a row here.
-- Records are NEVER updated or deleted — corrections are new rows.
-- Depends on: 002_invoice_history.sql (invoice_id FK, advisory — nullable).
-- =============================================================================

CREATE TABLE IF NOT EXISTS audit_log (
    log_id        UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Nullable FK: audit events can exist for runs that failed before invoice_history
    -- was populated (e.g. parse errors). Do not block log writes on FK constraint.
    invoice_id    UUID        REFERENCES invoice_history (invoice_id) ON DELETE SET NULL,
    -- Dot-namespaced event type: 'gate.ofac.fail', 'route.block', 'human.approve', etc.
    event_type    TEXT        NOT NULL,
    -- 'system' | 'llm' | Slack user ID (for human decisions)
    actor         TEXT        NOT NULL,
    -- Arbitrary structured payload; schema varies per event_type.
    details       JSONB       NOT NULL DEFAULT '{}',
    -- EAT (UTC+3) timestamp. Always set explicitly by the application layer
    -- so timezone is consistent regardless of DB server TZ setting.
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Primary access pattern: fetch all events for a given invoice in order.
CREATE INDEX IF NOT EXISTS idx_audit_invoice_id
    ON audit_log (invoice_id);

-- Secondary access pattern: time-range queries for compliance reporting.
CREATE INDEX IF NOT EXISTS idx_audit_created_at
    ON audit_log (created_at DESC);

-- Composite index to support event_type filtering within an invoice scope.
CREATE INDEX IF NOT EXISTS idx_audit_invoice_event
    ON audit_log (invoice_id, event_type);
