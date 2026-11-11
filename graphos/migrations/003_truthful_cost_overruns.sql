-- Reservation admission is enforced under the run lock. Incurred provider spend
-- must remain recordable even when an adapter exceeds its authorization.
ALTER TABLE graphos_runs DROP CONSTRAINT graphos_runs_check;
ALTER TABLE graphos_runs DROP CONSTRAINT graphos_runs_valid_state;
ALTER TABLE graphos_runs ADD CONSTRAINT graphos_runs_valid_state
    CHECK (state IN ('ACTIVE','READY_FOR_RELEASE','RELEASED','EXHAUSTED','BUDGET_EXCEEDED','CANCELLED'));
ALTER TABLE graphos_attempts DROP CONSTRAINT graphos_attempts_valid_cost;
ALTER TABLE graphos_attempts ADD CONSTRAINT graphos_attempts_valid_cost
    CHECK (epoch > 0 AND (actual_cost IS NULL OR actual_cost >= 0));
