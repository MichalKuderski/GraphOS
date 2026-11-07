-- A consumed reservation is a conservative charge, not a settled provider total.
ALTER TABLE graphos_attempts ADD COLUMN cost_uncertain boolean NOT NULL DEFAULT false;
ALTER TABLE graphos_attempts ADD CONSTRAINT graphos_attempts_uncertain_build_cost
    CHECK (NOT cost_uncertain OR (kind = 'BUILD' AND state IN ('FAILED','EXPIRED','FENCED')));
CREATE INDEX graphos_attempts_uncertain_cost ON graphos_attempts(task_id)
    WHERE cost_uncertain;
ALTER TABLE graphos_runs DROP CONSTRAINT graphos_runs_valid_state;
ALTER TABLE graphos_runs ADD CONSTRAINT graphos_runs_valid_state
    CHECK (state IN ('ACTIVE','READY_FOR_RELEASE','RELEASED','EXHAUSTED',
                    'BUDGET_EXCEEDED','RECONCILIATION_REQUIRED','CANCELLED'));

-- Legacy failures did not distinguish known totals from estimated charges.
-- Pause conservatively unless an authoritative receipt already settled them.
UPDATE graphos_attempts a SET cost_uncertain = true
WHERE a.kind = 'BUILD' AND a.state IN ('FAILED','EXPIRED','FENCED')
  AND NOT EXISTS (SELECT 1 FROM graphos_cost_receipts c WHERE c.attempt_id = a.id);
UPDATE graphos_runs r SET state = 'RECONCILIATION_REQUIRED', updated_at = clock_timestamp()
WHERE r.state NOT IN ('CANCELLED','BUDGET_EXCEEDED')
  AND EXISTS (SELECT 1 FROM graphos_attempts a JOIN graphos_tasks t ON t.id = a.task_id
              WHERE t.run_id = r.id AND a.cost_uncertain);
