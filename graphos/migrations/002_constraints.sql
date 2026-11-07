ALTER TABLE graphos_runs ADD CONSTRAINT graphos_runs_valid_state
    CHECK (state IN ('ACTIVE','READY_FOR_RELEASE','RELEASED','EXHAUSTED','CANCELLED'));
ALTER TABLE graphos_tasks ADD CONSTRAINT graphos_tasks_valid_state
    CHECK (state IN ('PENDING','BUILDING','SUBMITTED','VERIFYING','ACCEPTED','EXHAUSTED','INVALIDATED','CANCELLED'));
ALTER TABLE graphos_tasks ADD CONSTRAINT graphos_tasks_valid_counters
    CHECK (revision > 0 AND epoch >= 0 AND state_version >= 0 AND build_attempts >= 0 AND verify_attempts >= 0);
ALTER TABLE graphos_tasks ADD CONSTRAINT graphos_tasks_active_attempt
    FOREIGN KEY(active_attempt_id) REFERENCES graphos_attempts(id);
ALTER TABLE graphos_attempts ADD CONSTRAINT graphos_attempts_valid_state
    CHECK (state IN ('ACTIVE','SUBMITTED','FAILED','VERIFIED','EXPIRED','FENCED'));
ALTER TABLE graphos_attempts ADD CONSTRAINT graphos_attempts_valid_cost
    CHECK (epoch > 0 AND (actual_cost IS NULL OR actual_cost BETWEEN 0 AND reservation));
ALTER TABLE graphos_effects ADD CONSTRAINT graphos_effects_valid_state
    CHECK (state IN ('PREPARED','DISPATCHED','UNKNOWN','CONFIRMED','NOT_APPLIED'));
ALTER TABLE graphos_effect_attempts ADD CONSTRAINT graphos_effect_attempts_valid_outcome
    CHECK (outcome IN ('DISPATCHED','UNKNOWN','CONFIRMED','NOT_APPLIED'));
CREATE INDEX graphos_runs_recent ON graphos_runs(created_at DESC, id);
CREATE INDEX graphos_outbox_pending ON graphos_outbox(event_id) WHERE dispatched_at IS NULL;
CREATE INDEX graphos_tasks_active_attempt_ref ON graphos_tasks(active_attempt_id)
    WHERE active_attempt_id IS NOT NULL;
