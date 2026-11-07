"""Fault and concurrency checks against PostgreSQL, never an in-memory substitute."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
import uuid

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import pytest

from graphos.ledger import Conflict, Ledger


H = "1" * 64
CANDIDATE = "2" * 64
EVIDENCE = "3" * 64


@pytest.fixture(scope="module")
def ledger_dsn():
    dsn = os.environ.get("GRAPHOS_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("GRAPHOS_TEST_DATABASE_URL is required for real PostgreSQL tests")
    schema = "test_ledger_" + uuid.uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(dsn, options=f"-csearch_path={schema}")
    Ledger(isolated).migrate()
    yield isolated
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
def ledger(ledger_dsn):
    return Ledger(ledger_dsn)


def spec(tasks=None, attempts=3):
    return {"name": "ledger fault tests", "profile": "static-web", "requirements": ["deterministic test requirement"], "tasks": tasks or [{"key": "app", "objective": "build a test artifact", "depends_on": []}], "suite_hash": H, "policy_hash": H, "max_attempts": attempts}


def run(ledger, budget=100, tasks=None, attempts=3):
    return ledger.create_run(spec(tasks, attempts), budget, uuid.uuid4().hex)


def submit(ledger, claim, cost=1, candidate=CANDIDATE):
    return ledger.submit_build(claim["run_id"], claim["task_id"], claim["token"], claim["epoch"], claim["revision"], claim["input_hash"], candidate, cost, {"mode": "fixture", "live_model": False})


def verify(ledger, claim, passed=True, **overrides):
    args = {key: claim[key] for key in ("run_id", "task_id", "token", "epoch", "revision", "input_hash", "candidate_hash", "suite_hash", "policy_hash")}
    args.update(passed=passed, evidence_hash=EVIDENCE, report={"passed": passed, "mode": "trusted-test-fixture"})
    args.update(overrides)
    return ledger.submit_verification(**args)


def test_migration_is_idempotent_and_admission_survives_restart(ledger, ledger_dsn):
    ledger.migrate()
    key = uuid.uuid4().hex
    original = ledger.create_run(spec(), 100, key)
    restarted = Ledger(ledger_dsn)
    repeated = restarted.create_run(spec(), 100, key)
    assert repeated["id"] == original["id"]
    assert len(repeated["events"]) == 1
    with pytest.raises(Conflict, match="different payload"):
        restarted.create_run(spec(), 101, key)
    assert restarted.get_run(original["id"])["budget"] == 100


@pytest.mark.parametrize("tasks", [
    [{"key": "a", "objective": "a", "depends_on": ["missing"]}],
    [{"key": "a", "objective": "a", "depends_on": ["b"]}, {"key": "b", "objective": "b", "depends_on": ["a"]}],
    [{"key": "a", "objective": "a", "depends_on": []}, {"key": "a", "objective": "a", "depends_on": []}],
])
def test_invalid_dependency_graphs_rejected(ledger, tasks):
    with pytest.raises(Conflict):
        run(ledger, tasks=tasks)


def test_unbounded_and_invalid_values_rejected(ledger):
    for budget in (True, -1, 0, 10**16):
        with pytest.raises(Conflict):
            run(ledger, budget=budget)
    bad = spec()
    bad["tasks"] = []
    with pytest.raises(Conflict):
        ledger.create_run(bad, 10, uuid.uuid4().hex)
    bad = spec()
    bad["suite_hash"] = "not-a-hash"
    with pytest.raises(Conflict):
        ledger.create_run(bad, 10, uuid.uuid4().hex)


def test_concurrent_claims_cannot_share_one_task(ledger, ledger_dsn):
    current = run(ledger)
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = list(pool.map(lambda n: Ledger(ledger_dsn).claim_build(current["id"], f"worker-{n}", 10), range(8)))
    assert sum(claim is not None for claim in claims) == 1
    snapshot = ledger.get_run(current["id"])
    assert snapshot["reserved"] == 10
    assert len([event for event in snapshot["events"] if event["kind"] == "BUILD_CLAIMED"]) == 1


def test_concurrent_budget_reservations_are_atomic(ledger, ledger_dsn):
    current = run(ledger, tasks=[{"key": str(i), "objective": "test", "depends_on": []} for i in range(8)])
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = list(pool.map(lambda n: Ledger(ledger_dsn).claim_build(current["id"], f"worker-{n}", 60), range(8)))
    assert sum(claim is not None for claim in claims) == 1
    snapshot = ledger.get_run(current["id"])
    assert snapshot["spent"] + snapshot["reserved"] == 60


def test_concurrent_admission_has_one_durable_run(ledger, ledger_dsn):
    key = uuid.uuid4().hex
    with ThreadPoolExecutor(max_workers=6) as pool:
        records = list(pool.map(lambda _: Ledger(ledger_dsn).create_run(spec(), 100, key), range(6)))
    assert len({record["id"] for record in records}) == 1
    assert len(ledger.get_run(records[0]["id"])["events"]) == 1


def test_build_submission_is_idempotent_not_acceptance(ledger):
    current = run(ledger)
    claim = ledger.claim_build(current["id"], "builder", 20)
    first = submit(ledger, claim, cost=7)
    repeated = submit(ledger, claim, cost=7)
    assert first["state"] == repeated["state"] == "SUBMITTED"
    assert ledger.get_run(current["id"])["spent"] == 7
    assert ledger.get_run(current["id"])["reserved"] == 0
    assert ledger.claim_verify(current["id"], "builder") is None
    with pytest.raises(Conflict):
        submit(ledger, claim, cost=8)
    with pytest.raises(Conflict):
        ledger.release_manifest(current["id"])


def test_known_cost_above_reservation_is_recorded_and_blocks_dispatch(ledger):
    current = run(ledger)
    claim = ledger.claim_build(current["id"], "builder", 1)
    submit(ledger, claim, cost=2)
    snapshot = ledger.get_run(current["id"])
    assert snapshot["spent"] == 2 and snapshot["reserved"] == 0
    assert snapshot["state"] == "BUDGET_EXCEEDED"
    assert any(event["kind"] == "COST_OVERRUN" for event in snapshot["events"])
    assert ledger.claim_build(current["id"], "builder", 1) is None
    assert ledger.claim_verify(current["id"], "verifier") is None
    with pytest.raises(Conflict):
        ledger.revise_run(current["id"], spec(), 1)
    with pytest.raises(Conflict):
        ledger.prepare_effect(current["id"], "key", H, True)
    with pytest.raises(Conflict):
        ledger.release_manifest(current["id"])


def test_over_budget_actual_failure_is_not_hidden_and_sibling_can_settle(ledger):
    current = run(ledger, budget=10, tasks=[{"key": "a", "objective": "a", "depends_on": []}, {"key": "b", "objective": "b", "depends_on": []}])
    ledger.prepare_effect(current["id"], "key", H, True)
    a = ledger.claim_build(current["id"], "worker-a", 1)
    b = ledger.claim_build(current["id"], "worker-b", 2)
    ledger.fail_build(current["id"], a["task_id"], a["token"], a["epoch"], "known provider overrun", 20, cost_known=True)
    assert ledger.get_run(current["id"])["spent"] == 20
    submit(ledger, b, cost=1)
    snapshot = ledger.get_run(current["id"])
    assert snapshot["state"] == "BUDGET_EXCEEDED" and snapshot["spent"] == 21 and snapshot["reserved"] == 0
    with pytest.raises(Conflict):
        ledger.begin_effect(current["id"], "key")
    cancelled = ledger.cancel_run(current["id"])
    assert cancelled["spent"] == 21 and cancelled["state"] == "CANCELLED"


def test_expired_worker_is_fenced_and_reservation_consumed(ledger, ledger_dsn):
    current = run(ledger)
    old = ledger.claim_build(current["id"], "old-worker", 30)
    # Accelerate server time at the persisted lease boundary, without local clocks.
    with psycopg.connect(ledger_dsn) as conn:
        conn.execute("UPDATE graphos_attempts SET expires_at=clock_timestamp()-interval '1 second' WHERE id=%s", (old["attempt_id"],))
    restarted = Ledger(ledger_dsn)
    assert restarted.claim_build(current["id"], "replacement", 30) is None
    with pytest.raises(Conflict, match="expired or fenced"):
        submit(ledger, old)
    snapshot = restarted.get_run(current["id"])
    assert snapshot["spent"] == 30 and snapshot["reserved"] == 0
    assert snapshot["state"] == "RECONCILIATION_REQUIRED"
    assert snapshot["uncertain_cost_attempts"][0]["attempt_id"] == old["attempt_id"]
    restarted.reconcile_cost(current["id"], old["attempt_id"], uuid.uuid4().hex, 30)
    new = restarted.claim_build(current["id"], "replacement", 30)
    assert new["epoch"] > old["epoch"]
    submit(restarted, new, cost=4)
    assert restarted.get_run(current["id"])["spent"] == 34


def test_verification_binds_candidate_suite_policy_and_exact_revision(ledger):
    current = run(ledger)
    build = ledger.claim_build(current["id"], "builder", 10)
    submit(ledger, build)
    check = ledger.claim_verify(current["id"], "independent-verifier")
    for field in ("candidate_hash", "suite_hash", "policy_hash", "input_hash"):
        with pytest.raises(Conflict):
            verify(ledger, check, **{field: "f" * 64})
    accepted = verify(ledger, check)
    assert accepted["state"] == "ACCEPTED"
    manifest = ledger.release_manifest(current["id"])
    assert manifest == ledger.release_manifest(current["id"])
    assert manifest["tasks"][0]["candidate_hash"] == CANDIDATE
    assert manifest["tasks"][0]["evidence_hash"] == EVIDENCE
    assert manifest["tasks"][0]["provenance"]["mode"] == "fixture"
    assert verify(ledger, check)["state"] == "ACCEPTED"


def test_revision_during_verification_invalidates_old_evidence(ledger, ledger_dsn):
    current = run(ledger)
    build = ledger.claim_build(current["id"], "builder", 20)
    submit(ledger, build)
    check = ledger.claim_verify(current["id"], "verifier")
    revised_spec = spec()
    revised_spec["requirements"] = ["different requirement"]
    updated = ledger.revise_run(current["id"], revised_spec, 1)
    assert updated["revision"] == 2
    with pytest.raises(Conflict):
        verify(Ledger(ledger_dsn), check)
    with pytest.raises(Conflict):
        ledger.release_manifest(current["id"])
    with psycopg.connect(ledger_dsn) as conn:
        assert conn.execute("SELECT state FROM graphos_tasks WHERE id=%s", (build["task_id"],)).fetchone()[0] == "INVALIDATED"
    assert updated["tasks"][0]["state"] == "PENDING"


def test_expired_verifier_cannot_submit_after_replacement_claim(ledger, ledger_dsn):
    current = run(ledger)
    submit(ledger, ledger.claim_build(current["id"], "builder", 10))
    old = ledger.claim_verify(current["id"], "verifier-old")
    with psycopg.connect(ledger_dsn) as conn:
        conn.execute("UPDATE graphos_attempts SET expires_at=clock_timestamp()-interval '1 second' WHERE id=%s", (old["attempt_id"],))
    new = ledger.claim_verify(current["id"], "verifier-new")
    assert new["epoch"] > old["epoch"]
    with pytest.raises(Conflict):
        verify(ledger, old)
    assert verify(ledger, new)["state"] == "ACCEPTED"


def test_revision_invalidates_release_receipt_but_retains_history(ledger, ledger_dsn):
    current = run(ledger)
    submit(ledger, ledger.claim_build(current["id"], "builder", 10))
    verify(ledger, ledger.claim_verify(current["id"], "verifier"))
    released = ledger.release_manifest(current["id"])
    ledger.revise_run(current["id"], spec(), 1)
    with pytest.raises(Conflict):
        ledger.release_manifest(current["id"])
    with psycopg.connect(ledger_dsn) as conn:
        row = conn.execute("SELECT manifest_hash,invalidated_at FROM graphos_releases WHERE id=%s", (released["release_id"],)).fetchone()
    assert row[0] == released["manifest_hash"] and row[1] is not None


def test_release_rejects_stale_artifact_preflight_snapshot(ledger):
    current = run(ledger)
    submit(ledger, ledger.claim_build(current["id"], "builder", 10))
    verify(ledger, ledger.claim_verify(current["id"], "verifier"))
    preflight = ledger.get_run(current["id"])
    revised = ledger.revise_run(current["id"], spec(), 1)
    submit(ledger, ledger.claim_build(current["id"], "builder", 10))
    verify(ledger, ledger.claim_verify(current["id"], "verifier"))
    with pytest.raises(Conflict, match="preflight snapshot is stale"):
        ledger.release_manifest(current["id"], preflight["revision"], preflight["spec_hash"])
    with pytest.raises(Conflict, match="preflight snapshot is stale"):
        ledger.release_manifest(current["id"], revised["revision"], "f" * 64)
    assert ledger.release_manifest(current["id"], revised["revision"], revised["spec_hash"])["revision"] == 2


def test_revise_active_build_consumes_reservation_and_preserves_budget(ledger):
    current = run(ledger)
    old = ledger.claim_build(current["id"], "builder", 40)
    revised = ledger.revise_run(current["id"], spec(), 1)
    assert revised["spent"] == 40 and revised["reserved"] == 0
    with pytest.raises(Conflict):
        submit(ledger, old)
    with pytest.raises(Conflict):
        ledger.revise_run(current["id"], spec(), 1)


def test_dependency_only_unlocks_after_acceptance(ledger):
    current = run(ledger, tasks=[{"key": "a", "objective": "foundation", "depends_on": []}, {"key": "b", "objective": "dependent", "depends_on": ["a"]}])
    a = ledger.claim_build(current["id"], "builder", 10)
    assert a["task_key"] == "a"
    submit(ledger, a)
    assert ledger.claim_build(current["id"], "builder-2", 10) is None
    verify(ledger, ledger.claim_verify(current["id"], "verifier"))
    b = ledger.claim_build(current["id"], "builder-2", 10)
    assert b["task_key"] == "b" and b["dependencies"] == {"a": CANDIDATE}


def test_artifact_authorization_is_bound_to_current_lease_and_consumed_inputs(ledger, ledger_dsn):
    current = run(ledger, tasks=[{"key": "a", "objective": "foundation", "depends_on": []}, {"key": "b", "objective": "dependent", "depends_on": ["a"]}])
    a = ledger.claim_build(current["id"], "builder-a", 10)
    with pytest.raises(Conflict):
        ledger.authorize_artifact(current["id"], a["task_id"], a["token"], a["epoch"], CANDIDATE, "BUILD")
    submit(ledger, a)
    checker = ledger.claim_verify(current["id"], "verifier")
    ledger.authorize_artifact(current["id"], checker["task_id"], checker["token"], checker["epoch"], CANDIDATE, "VERIFY")
    with pytest.raises(Conflict):
        ledger.authorize_artifact(current["id"], checker["task_id"], checker["token"], checker["epoch"], EVIDENCE, "VERIFY")
    with pytest.raises(Conflict):
        ledger.authorize_artifact(current["id"], checker["task_id"], checker["token"], checker["epoch"], CANDIDATE, "BUILD")
    verify(ledger, checker)
    b = ledger.claim_build(current["id"], "builder-b", 10)
    ledger.authorize_artifact(current["id"], b["task_id"], b["token"], b["epoch"], CANDIDATE, "BUILD")
    with pytest.raises(Conflict):
        ledger.authorize_artifact(current["id"], b["task_id"], "wrong-token", b["epoch"], CANDIDATE, "BUILD")
    with psycopg.connect(ledger_dsn) as conn:
        conn.execute("UPDATE graphos_attempts SET expires_at=clock_timestamp()-interval '1 second' WHERE id=%s", (b["attempt_id"],))
    with pytest.raises(Conflict):
        ledger.authorize_artifact(current["id"], b["task_id"], b["token"], b["epoch"], CANDIDATE, "BUILD")


def test_repair_attempts_are_bounded(ledger):
    current = run(ledger, attempts=1)
    build = ledger.claim_build(current["id"], "builder", 10)
    submit(ledger, build)
    failed = verify(ledger, ledger.claim_verify(current["id"], "verifier"), passed=False)
    assert failed["state"] == "EXHAUSTED"
    assert ledger.get_run(current["id"])["state"] == "EXHAUSTED"
    assert ledger.claim_build(current["id"], "builder", 10) is None


def test_exhausted_sibling_does_not_strand_current_build_lease(ledger):
    current = run(ledger, tasks=[{"key": "a", "objective": "a", "depends_on": []}, {"key": "b", "objective": "b", "depends_on": []}], attempts=1)
    a = ledger.claim_build(current["id"], "worker-a", 10)
    b = ledger.claim_build(current["id"], "worker-b", 20)
    ledger.fail_build(current["id"], a["task_id"], a["token"], a["epoch"], "exhausted", 1, cost_known=True)
    assert ledger.get_run(current["id"])["state"] == "EXHAUSTED"
    assert submit(ledger, b, cost=2)["state"] == "SUBMITTED"
    snapshot = ledger.get_run(current["id"])
    assert snapshot["spent"] == 3 and snapshot["reserved"] == 0
    assert ledger.claim_build(current["id"], "replacement", 10) is None


def test_cancellation_fences_workers_but_effects_remain_reconcilable(ledger):
    current = run(ledger)
    claim = ledger.claim_build(current["id"], "builder", 30)
    ledger.prepare_effect(current["id"], "example-effect", H, False)
    effect = ledger.begin_effect(current["id"], "example-effect")
    cancelled = ledger.cancel_run(current["id"])
    assert cancelled["spent"] == 30 and cancelled["reserved"] == 0
    with pytest.raises(Conflict):
        submit(ledger, claim)
    assert ledger.claim_build(current["id"], "builder", 10) is None
    resolved = ledger.resolve_effect(current["id"], "example-effect", effect["attempt"], effect["token"], "CONFIRMED")
    assert resolved["state"] == "CONFIRMED"
    with pytest.raises(Conflict):
        ledger.begin_effect(current["id"], "example-effect")


def test_unknown_non_deduplicated_effect_never_blindly_retries(ledger):
    current = run(ledger)
    ledger.prepare_effect(current["id"], "key", H, False)
    effect = ledger.begin_effect(current["id"], "key")
    with pytest.raises(Conflict):
        ledger.begin_effect(current["id"], "key")
    ledger.resolve_effect(current["id"], "key", effect["attempt"], effect["token"], "UNKNOWN")
    with pytest.raises(Conflict):
        ledger.begin_effect(current["id"], "key")
    # An authoritative adapter reconciliation is represented by NOT_APPLIED.
    ledger.resolve_effect(current["id"], "key", effect["attempt"], effect["token"], "NOT_APPLIED")
    assert ledger.begin_effect(current["id"], "key")["attempt"] == 2


def test_stale_effect_receipt_cannot_clear_new_uncertainty(ledger):
    current = run(ledger)
    ledger.prepare_effect(current["id"], "key", H, True)
    old = ledger.begin_effect(current["id"], "key")
    new = ledger.begin_effect(current["id"], "key")
    with pytest.raises(Conflict, match="stale effect receipt"):
        ledger.resolve_effect(current["id"], "key", old["attempt"], old["token"], "NOT_APPLIED")
    assert ledger.get_run(current["id"])["effects"][0]["state"] == "DISPATCHED"
    ledger.resolve_effect(current["id"], "key", new["attempt"], new["token"], "CONFIRMED")
    with pytest.raises(Conflict):
        ledger.prepare_effect(current["id"], "key", "f" * 64, True)
    with pytest.raises(Conflict):
        ledger.resolve_effect(current["id"], "key", new["attempt"], new["token"], "UNKNOWN")


def test_lost_effect_response_can_reconcile_after_restart_and_cancel(ledger, ledger_dsn):
    current = run(ledger)
    ledger.prepare_effect(current["id"], "key", H, False)
    lost = ledger.begin_effect(current["id"], "key")
    ledger.cancel_run(current["id"])
    restarted = Ledger(ledger_dsn)
    receipt = restarted.claim_effect_reconciliation(current["id"], "key")
    assert receipt["attempt"] == lost["attempt"] == 1
    assert receipt["state"] == "UNKNOWN" and receipt["token"] != lost["token"]
    with pytest.raises(Conflict):
        restarted.resolve_effect(current["id"], "key", 1, lost["token"], "NOT_APPLIED")
    assert restarted.resolve_effect(current["id"], "key", 1, receipt["token"], "CONFIRMED")["state"] == "CONFIRMED"
    with pytest.raises(Conflict):
        restarted.begin_effect(current["id"], "key")
    with pytest.raises(Conflict):
        restarted.release_manifest(current["id"])


def test_revised_effect_can_reconcile_but_never_redispatch(ledger):
    current = run(ledger)
    ledger.prepare_effect(current["id"], "key", H, False)
    ledger.begin_effect(current["id"], "key")
    ledger.revise_run(current["id"], spec(), 1)
    receipt = ledger.claim_effect_reconciliation(current["id"], "key")
    assert receipt["revision"] == 1
    ledger.resolve_effect(current["id"], "key", receipt["attempt"], receipt["token"], "NOT_APPLIED")
    with pytest.raises(Conflict):
        ledger.begin_effect(current["id"], "key")


def test_events_have_atomic_outbox_and_snapshots_never_contain_tokens(ledger, ledger_dsn):
    current = run(ledger)
    claim = ledger.claim_build(current["id"], "builder", 10)
    ledger.prepare_effect(current["id"], "key", H, True)
    effect = ledger.begin_effect(current["id"], "key")
    snapshot = ledger.get_run(current["id"])
    text = str(snapshot)
    assert claim["token"] not in text and effect["token"] not in text and "token_hash" not in text
    with psycopg.connect(ledger_dsn) as conn:
        counts = conn.execute("SELECT count(*), count(o.event_id) FROM graphos_events e LEFT JOIN graphos_outbox o ON o.event_id=e.id WHERE e.run_id=%s", (current["id"],)).fetchone()
    assert counts[0] == counts[1] == len(snapshot["events"])


def test_late_cost_receipt_refunds_expired_charge_without_accepting_result(ledger, ledger_dsn):
    current = run(ledger)
    lost = ledger.claim_build(current["id"], "lost-worker", 30)
    with psycopg.connect(ledger_dsn) as conn:
        conn.execute("UPDATE graphos_attempts SET expires_at=clock_timestamp()-interval '1 second' WHERE id=%s", (lost["attempt_id"],))
    receipt_id = uuid.uuid4().hex
    receipt = Ledger(ledger_dsn).reconcile_cost(current["id"], lost["attempt_id"], receipt_id, 7)
    assert receipt["previous_charge"] == 30 and receipt["delta"] == -23 and receipt["spent"] == 7
    snapshot = ledger.get_run(current["id"])
    assert snapshot["reserved"] == 0 and snapshot["tasks"][0]["state"] == "PENDING"
    assert snapshot["tasks"][0]["candidate_hash"] is None
    with pytest.raises(Conflict):
        submit(ledger, lost)
    repeated = Ledger(ledger_dsn).reconcile_cost(current["id"], lost["attempt_id"], receipt_id, 7)
    assert repeated == receipt
    assert len(ledger.get_run(current["id"])["events"]) == len(snapshot["events"])


def test_cost_receipt_conflicts_are_not_silent_corrections(ledger):
    current = run(ledger)
    build = ledger.claim_build(current["id"], "builder", 30)
    with pytest.raises(Conflict, match="settled or expired"):
        ledger.reconcile_cost(current["id"], build["attempt_id"], uuid.uuid4().hex, 7)
    submit(ledger, build, cost=10)
    receipt_id = uuid.uuid4().hex
    ledger.reconcile_cost(current["id"], build["attempt_id"], receipt_id, 7)
    with pytest.raises(Conflict, match="different payload"):
        ledger.reconcile_cost(current["id"], build["attempt_id"], receipt_id, 8)
    with pytest.raises(Conflict, match="already has an authoritative"):
        ledger.reconcile_cost(current["id"], build["attempt_id"], uuid.uuid4().hex, 8)
    other = run(ledger)
    with pytest.raises(Conflict):
        ledger.reconcile_cost(other["id"], build["attempt_id"], uuid.uuid4().hex, 7)
    checker = ledger.claim_verify(current["id"], "verifier")
    with pytest.raises(Conflict):
        ledger.reconcile_cost(current["id"], checker["attempt_id"], uuid.uuid4().hex, 0)
    assert ledger.get_run(current["id"])["spent"] == 7


def test_old_revision_uncertainty_blocks_current_graph_until_reconciled(ledger):
    current = run(ledger)
    old = ledger.claim_build(current["id"], "old-builder", 30)
    revised = ledger.revise_run(current["id"], spec(), 1)
    assert revised["state"] == "RECONCILIATION_REQUIRED"
    assert ledger.claim_build(current["id"], "current-builder", 10) is None
    before = ledger.get_run(current["id"])
    receipt = ledger.reconcile_cost(current["id"], old["attempt_id"], uuid.uuid4().hex, 7)
    after = ledger.get_run(current["id"])
    assert receipt["attempt_revision"] == 1 and receipt["accounting_revision"] == 2
    assert after["revision"] == revised["revision"] == before["revision"]
    assert after["spec_hash"] == before["spec_hash"] and after["tasks"] == before["tasks"]
    assert after["spent"] == 7 and after["reserved"] == 0 and after["state"] == "ACTIVE"
    assert after["uncertain_cost_attempts"] == []
    active = ledger.claim_build(current["id"], "current-builder", 10)
    assert submit(ledger, active)["state"] == "SUBMITTED"


def test_late_cost_overrun_blocks_current_revision_without_reviving_cancelled_run(ledger):
    current = run(ledger, budget=10)
    old = ledger.claim_build(current["id"], "builder", 2)
    ledger.revise_run(current["id"], spec(), 1)
    receipt = ledger.reconcile_cost(current["id"], old["attempt_id"], uuid.uuid4().hex, 20)
    assert receipt["spent"] == 20 and receipt["state"] == "BUDGET_EXCEEDED"
    assert ledger.claim_build(current["id"], "builder", 1) is None
    with pytest.raises(Conflict):
        ledger.revise_run(current["id"], spec(), 2)
    cancelled = run(ledger, budget=10)
    attempt = ledger.claim_build(cancelled["id"], "builder", 2)
    ledger.cancel_run(cancelled["id"])
    receipt = ledger.reconcile_cost(cancelled["id"], attempt["attempt_id"], uuid.uuid4().hex, 20)
    snapshot = ledger.get_run(cancelled["id"])
    assert receipt["state"] == snapshot["state"] == "CANCELLED" and snapshot["spent"] == 20
    assert any(event["kind"] == "COST_OVERRUN" for event in snapshot["events"])
    assert ledger.claim_build(cancelled["id"], "builder", 1) is None


def test_concurrent_duplicate_cost_receipts_apply_delta_once(ledger, ledger_dsn):
    current = run(ledger)
    build = ledger.claim_build(current["id"], "builder", 30)
    submit(ledger, build, cost=10)
    receipt_id = uuid.uuid4().hex
    with ThreadPoolExecutor(max_workers=6) as pool:
        receipts = list(pool.map(lambda _: Ledger(ledger_dsn).reconcile_cost(current["id"], build["attempt_id"], receipt_id, 7), range(6)))
    assert all(receipt == receipts[0] for receipt in receipts)
    snapshot = ledger.get_run(current["id"])
    assert snapshot["spent"] == 7
    assert len([event for event in snapshot["events"] if event["kind"] == "COST_RECONCILED"]) == 1


def test_unknown_failure_requires_reconciliation_even_when_budget_remains(ledger, ledger_dsn):
    current = run(ledger)
    claim = ledger.claim_build(current["id"], "builder", 30)
    ledger.prepare_effect(current["id"], "queued-effect", H, True)
    # An absent/unknown provider total cannot refund the reserved authorization.
    failed = ledger.fail_build(current["id"], claim["task_id"], claim["token"], claim["epoch"],
                               "remote request status unknown", 0, cost_known=False)
    repeated = ledger.fail_build(current["id"], claim["task_id"], claim["token"], claim["epoch"],
                                 "remote request status unknown", 0, cost_known=False)
    assert repeated == failed
    restarted = Ledger(ledger_dsn)
    snapshot = restarted.get_run(current["id"])
    assert snapshot["spent"] == 30 and snapshot["reserved"] == 0
    assert snapshot["state"] == "RECONCILIATION_REQUIRED"
    assert restarted.claim_build(current["id"], "retry", 10) is None
    assert restarted.claim_verify(current["id"], "verifier") is None
    with pytest.raises(Conflict):
        restarted.begin_effect(current["id"], "queued-effect")
    with pytest.raises(Conflict):
        restarted.prepare_effect(current["id"], "new-effect", H, True)
    with pytest.raises(Conflict):
        restarted.release_manifest(current["id"])
    receipt = restarted.reconcile_cost(current["id"], claim["attempt_id"], uuid.uuid4().hex, 5)
    assert receipt["state"] == "ACTIVE" and receipt["spent"] == 5
    assert restarted.claim_build(current["id"], "retry", 10) is not None


def test_all_uncertain_attempts_must_clear_and_current_sibling_can_settle(ledger):
    current = run(ledger, tasks=[{"key": key, "objective": key, "depends_on": []} for key in ("a", "b", "c")])
    a = ledger.claim_build(current["id"], "a", 10)
    b = ledger.claim_build(current["id"], "b", 10)
    c = ledger.claim_build(current["id"], "c", 10)
    for claim in (a, b):
        ledger.fail_build(current["id"], claim["task_id"], claim["token"], claim["epoch"], "unknown", 10, cost_known=False)
    # Pause prevents new dispatch, not settlement of work already authorized.
    assert submit(ledger, c, cost=1)["state"] == "SUBMITTED"
    first = ledger.reconcile_cost(current["id"], a["attempt_id"], uuid.uuid4().hex, 2)
    assert first["state"] == "RECONCILIATION_REQUIRED"
    assert ledger.claim_build(current["id"], "retry", 10) is None
    final = ledger.reconcile_cost(current["id"], b["attempt_id"], uuid.uuid4().hex, 3)
    assert final["state"] == "ACTIVE" and final["spent"] == 6


def test_cost_receipt_cannot_revive_exhaustion_cancellation_or_overrun(ledger):
    exhausted = run(ledger, attempts=1)
    attempt = ledger.claim_build(exhausted["id"], "builder", 10)
    ledger.fail_build(exhausted["id"], attempt["task_id"], attempt["token"], attempt["epoch"], "unknown", 10)
    assert ledger.reconcile_cost(exhausted["id"], attempt["attempt_id"], uuid.uuid4().hex, 0)["state"] == "EXHAUSTED"
    assert ledger.claim_build(exhausted["id"], "retry", 1) is None

    cancelled = run(ledger)
    attempt = ledger.claim_build(cancelled["id"], "builder", 10)
    ledger.cancel_run(cancelled["id"])
    assert ledger.reconcile_cost(cancelled["id"], attempt["attempt_id"], uuid.uuid4().hex, 0)["state"] == "CANCELLED"

    overrun = run(ledger)
    attempt = ledger.claim_build(overrun["id"], "builder", 10)
    ledger.fail_build(overrun["id"], attempt["task_id"], attempt["token"], attempt["epoch"], "known overrun", 20, cost_known=True)
    assert ledger.reconcile_cost(overrun["id"], attempt["attempt_id"], uuid.uuid4().hex, 5)["state"] == "BUDGET_EXCEEDED"
