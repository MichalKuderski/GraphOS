-- Narrow append-only capture authority survives build fencing for recovery.
-- Captured identifiers/runtime usage are not fetched provider cost receipts.
CREATE TABLE graphos_receipt_grants (
    attempt_id text PRIMARY KEY REFERENCES graphos_attempts(id),
    token_hash text NOT NULL,
    session_id text UNIQUE,
    terminal_outcome text CHECK (terminal_outcome IN ('completed','failed','cancelled')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE graphos_model_receipts (
    attempt_id text NOT NULL REFERENCES graphos_receipt_grants(attempt_id),
    model_run_id text NOT NULL,
    model_id text NOT NULL,
    model_attempt integer NOT NULL CHECK (model_attempt = 0),
    generation_id text UNIQUE,
    usage jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (attempt_id, model_run_id)
);
CREATE TABLE graphos_attempt_receipt_events (
    attempt_id text NOT NULL REFERENCES graphos_receipt_grants(attempt_id),
    event_id text NOT NULL,
    identity_key text NOT NULL,
    payload_hash text NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (attempt_id, event_id),
    UNIQUE (attempt_id, identity_key)
);
