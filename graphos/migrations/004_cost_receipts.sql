-- One operator-asserted provider total per settled build attempt. Corrections
-- require a future explicit superseding-receipt policy; amounts are not replaced.
CREATE TABLE graphos_cost_receipts (
    receipt_id text PRIMARY KEY,
    run_id text NOT NULL REFERENCES graphos_runs(id),
    attempt_id text NOT NULL UNIQUE REFERENCES graphos_attempts(id),
    payload_hash text NOT NULL,
    actual_cost bigint NOT NULL CHECK (actual_cost >= 0),
    previous_charge bigint NOT NULL CHECK (previous_charge >= 0),
    delta bigint NOT NULL,
    attempt_revision integer NOT NULL CHECK (attempt_revision > 0),
    accounting_revision integer NOT NULL CHECK (accounting_revision > 0),
    result jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (delta = actual_cost - previous_charge)
);
CREATE INDEX graphos_cost_receipts_run ON graphos_cost_receipts(run_id, created_at);
