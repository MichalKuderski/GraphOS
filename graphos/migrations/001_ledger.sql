CREATE TABLE graphos_runs (
    id text PRIMARY KEY,
    idempotency_key text NOT NULL UNIQUE,
    admission_hash text NOT NULL,
    spec jsonb NOT NULL,
    spec_hash text NOT NULL,
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    state text NOT NULL DEFAULT 'ACTIVE',
    budget bigint NOT NULL CHECK (budget > 0),
    spent bigint NOT NULL DEFAULT 0 CHECK (spent >= 0),
    reserved bigint NOT NULL DEFAULT 0 CHECK (reserved >= 0),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (spent + reserved <= budget)
);
CREATE TABLE graphos_tasks (
    id text PRIMARY KEY,
    run_id text NOT NULL REFERENCES graphos_runs(id),
    revision integer NOT NULL,
    task_key text NOT NULL,
    objective text NOT NULL,
    depends_on jsonb NOT NULL,
    state text NOT NULL DEFAULT 'PENDING',
    state_version integer NOT NULL DEFAULT 0,
    epoch integer NOT NULL DEFAULT 0,
    build_attempts integer NOT NULL DEFAULT 0,
    verify_attempts integer NOT NULL DEFAULT 0,
    active_attempt_id text,
    input_hash text,
    candidate_hash text,
    producer_id text,
    evidence_hash text,
    verification jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE(run_id, revision, task_key)
);
CREATE INDEX graphos_tasks_dispatch ON graphos_tasks(run_id, revision, state);
CREATE TABLE graphos_attempts (
    id text PRIMARY KEY,
    task_id text NOT NULL REFERENCES graphos_tasks(id),
    kind text NOT NULL CHECK (kind IN ('BUILD', 'VERIFY')),
    epoch integer NOT NULL,
    worker_id text NOT NULL,
    token_hash text NOT NULL,
    state text NOT NULL DEFAULT 'ACTIVE',
    reservation bigint NOT NULL DEFAULT 0 CHECK (reservation >= 0),
    actual_cost bigint,
    expires_at timestamptz NOT NULL,
    input_hash text NOT NULL,
    candidate_hash text,
    submission_hash text,
    result jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE(task_id, epoch)
);
CREATE INDEX graphos_attempts_expiry ON graphos_attempts(expires_at) WHERE state = 'ACTIVE';
CREATE TABLE graphos_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id text NOT NULL REFERENCES graphos_runs(id),
    revision integer NOT NULL,
    kind text NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX graphos_events_run ON graphos_events(run_id, id);
CREATE TABLE graphos_outbox (
    event_id bigint PRIMARY KEY REFERENCES graphos_events(id),
    dispatched_at timestamptz,
    attempts integer NOT NULL DEFAULT 0
);
CREATE TABLE graphos_releases (
    id text PRIMARY KEY,
    run_id text NOT NULL REFERENCES graphos_runs(id),
    revision integer NOT NULL,
    manifest_hash text NOT NULL,
    manifest jsonb NOT NULL,
    invalidated_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE(run_id, revision)
);
CREATE TABLE graphos_effects (
    run_id text NOT NULL REFERENCES graphos_runs(id),
    operation_key text NOT NULL,
    revision integer NOT NULL,
    payload_hash text NOT NULL,
    receiver_deduplicates boolean NOT NULL,
    state text NOT NULL DEFAULT 'PREPARED',
    attempt integer NOT NULL DEFAULT 0,
    token_hash text,
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(run_id, operation_key)
);
CREATE TABLE graphos_effect_attempts (
    run_id text NOT NULL,
    operation_key text NOT NULL,
    attempt integer NOT NULL,
    token_hash text NOT NULL,
    outcome text NOT NULL DEFAULT 'DISPATCHED',
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(run_id, operation_key, attempt),
    FOREIGN KEY(run_id, operation_key) REFERENCES graphos_effects(run_id, operation_key)
);
