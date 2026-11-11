"""Durable narrow runtime receipts against PostgreSQL; no provider or Docker calls."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
import uuid

from fastapi.testclient import TestClient
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import pytest

from graphos.api import create_app
from graphos.config import Settings
from graphos.ledger import Conflict, Ledger, ReceiptAuthorizationError, _receipt_event


@pytest.fixture(scope="module")
def receipt_dsn():
    dsn = os.environ.get("GRAPHOS_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("GRAPHOS_TEST_DATABASE_URL is required for real PostgreSQL receipt tests")
    schema = "test_receipts_" + uuid.uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(dsn, options=f"-csearch_path={schema}")
    Ledger(isolated).migrate()
    yield isolated
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
def ledger(receipt_dsn):
    return Ledger(receipt_dsn)


def setup(ledger, siblings=False):
    spec = {"name": "Receipt recovery", "profile": "static-web", "requirements": ["test"],
            "tasks": [{"key": "app", "objective": "test", "depends_on": []}],
            "suite_hash": "a" * 64, "policy_hash": "b" * 64, "max_attempts": 3}
    if siblings:
        spec["tasks"].append({"key": "sibling", "objective": "test sibling", "depends_on": []})
    run = ledger.create_run(spec, 1000, uuid.uuid4().hex)
    claim = ledger.claim_build(run["id"], "builder:test", 100)
    return claim, issue_grant(ledger, claim)


def issue_grant(ledger, claim):
    grant = ledger.create_receipt_grant(**{key: claim[key] for key in
        ("run_id", "task_id", "token", "epoch", "revision", "input_hash")})
    grant["session_id"] = "session_" + uuid.uuid4().hex
    grant.update({key: claim[key] for key in ("epoch", "revision", "input_hash")})
    return grant


def event(grant, kind, model_run="run_0", **overrides):
    value = {"event_id": kind + ":" + model_run, "kind": kind, "session_id": grant["session_id"]}
    if kind == "session":
        value.update({key: grant[key] for key in ("task_id", "epoch", "revision", "input_hash")})
    if kind in {"model_started", "generation", "usage"}:
        value.update(model_run_id=model_run, model_id="openai/gpt-5.1-codex-mini", model_attempt=0)
    if kind == "generation":
        value["generation_id"] = "gen_" + grant["attempt_id"].replace("-", "")
    elif kind == "usage":
        value["usage"] = {"input_tokens": 20, "output_tokens": 8, "cache_read_tokens": 0,
            "cache_write_tokens": 0, "actual_cost_microdollars": 17,
            "generation_id": "gen_" + grant["attempt_id"].replace("-", ""), "finish_reason": "stop"}
    elif kind == "session_terminal":
        value["outcome"] = "completed"
    return {**value, **overrides}


def capture(ledger, grant, kind, **overrides):
    return ledger.capture_attempt_receipt(grant["run_id"], grant["attempt_id"],
        grant["capture_token"], event(grant, kind, **overrides))


def start(ledger, grant):
    capture(ledger, grant, "session")
    capture(ledger, grant, "model_started")


def aggregate(grant):
    usage = event(grant, "usage")["usage"]
    return {**{key: usage[key] for key in ("input_tokens", "output_tokens", "cache_read_tokens",
            "cache_write_tokens", "actual_cost_microdollars")}, "model_runs": 1,
            "cost_source": "eve_gateway_usage_events", "generations": [
                {"run_id": "run_0", "generation_id": usage["generation_id"], "finish_reason": "stop"}]}


def fail(ledger, claim, usage):
    return ledger.fail_build(claim["run_id"], claim["task_id"], claim["token"], claim["epoch"],
                            "invalid artifact", 17, cost_known=True, usage=usage)


def test_grant_retries_are_stable_and_store_only_derived_hash(ledger, receipt_dsn):
    claim, grant = setup(ledger)
    ledger.migrate()
    repeated = Ledger(receipt_dsn).create_receipt_grant(**{key: claim[key] for key in
        ("run_id", "task_id", "token", "epoch", "revision", "input_hash")})
    assert repeated["capture_token"] == grant["capture_token"] != claim["token"]
    with psycopg.connect(receipt_dsn) as conn:
        stored = conn.execute("SELECT token_hash FROM graphos_receipt_grants WHERE attempt_id=%s",
                              (claim["attempt_id"],)).fetchone()[0]
    assert stored not in {claim["token"], grant["capture_token"]}
    with pytest.raises(Conflict, match="lease binding"):
        ledger.create_receipt_grant(claim["run_id"], claim["task_id"], "wrong-token", claim["epoch"],
                                    claim["revision"], claim["input_hash"])


def test_registration_is_idempotent_and_conflicting_identity_is_rejected(ledger):
    _, grant = setup(ledger)
    assert capture(ledger, grant, "session")["duplicate"] is False
    assert capture(ledger, grant, "session")["duplicate"] is True
    with pytest.raises(Conflict, match="different payload"):
        capture(ledger, grant, "session", event_id="retry-session")
    with pytest.raises(Conflict, match="different payload"):
        capture(ledger, grant, "session", session_id="a-different-session")
    assert capture(ledger, grant, "model_started")["duplicate"] is False
    assert capture(ledger, grant, "model_started")["duplicate"] is True
    capture(ledger, grant, "generation")
    assert capture(ledger, grant, "generation")["duplicate"] is True
    with pytest.raises(Conflict, match="different payload"):
        capture(ledger, grant, "generation", generation_id="gen_different")
    with pytest.raises(Conflict, match="different payload"):
        capture(ledger, grant, "usage", event_id="generation:run_0")


def test_unknown_session_model_and_wrong_capability_cannot_append(ledger):
    _, grant = setup(ledger)
    with pytest.raises(ReceiptAuthorizationError):
        ledger.capture_attempt_receipt(grant["run_id"], grant["attempt_id"], "wrong",
                                       event(grant, "session"))
    with pytest.raises(Conflict, match="session"):
        capture(ledger, grant, "model_started")
    capture(ledger, grant, "session")
    with pytest.raises(Conflict, match="registered intent"):
        capture(ledger, grant, "generation")
    capture(ledger, grant, "model_started")
    with pytest.raises(Conflict, match="registered intent"):
        capture(ledger, grant, "generation", model_id="different/model")
    with pytest.raises(Conflict, match="session"):
        capture(ledger, grant, "generation", session_id="wrong-session")


@pytest.mark.parametrize("overrides", [
    {"task_id": "wrong-task"}, {"epoch": 2}, {"revision": 2}, {"input_hash": "f" * 64},
])
def test_session_bind_cannot_mix_grant_with_another_claim(ledger, overrides):
    _, grant = setup(ledger)
    with pytest.raises(Conflict, match="claimed input binding"):
        capture(ledger, grant, "session", **overrides)
    assert capture(ledger, grant, "session")["duplicate"] is False


def test_unresolved_model_blocks_another_provider_intent(ledger):
    _, grant = setup(ledger)
    start(ledger, grant)
    with pytest.raises(Conflict, match="unresolved"):
        capture(ledger, grant, "model_started", model_run="run_1")
    capture(ledger, grant, "usage")
    assert capture(ledger, grant, "model_started", model_run="run_1")["duplicate"] is False


def test_session_and_generation_cannot_be_rebound_across_attempts(ledger):
    _, first = setup(ledger)
    _, second = setup(ledger)
    start(ledger, first)
    with pytest.raises(Conflict, match="session is already bound"):
        capture(ledger, second, "session", session_id=first["session_id"])
    start(ledger, second)
    capture(ledger, first, "generation")
    with pytest.raises(Conflict, match="generation is already bound"):
        capture(ledger, second, "generation", generation_id=event(first, "generation")["generation_id"])


def test_concurrent_identical_provider_intent_has_one_first_ack(ledger, receipt_dsn):
    _, grant = setup(ledger)
    capture(ledger, grant, "session")
    with ThreadPoolExecutor(max_workers=4) as pool:
        replies = list(pool.map(lambda _: capture(Ledger(receipt_dsn), grant, "model_started"), range(4)))
    assert sum(not reply["duplicate"] for reply in replies) == 1


@pytest.mark.parametrize("fence", ["expire", "cancel", "revise"])
def test_late_receipts_survive_fencing_without_settling_or_releasing(ledger, receipt_dsn, fence):
    claim, grant = setup(ledger)
    start(ledger, grant)
    capture(ledger, grant, "generation")
    if fence == "expire":
        with psycopg.connect(receipt_dsn) as conn:
            conn.execute("UPDATE graphos_attempts SET expires_at=clock_timestamp()-interval '1 second' WHERE id=%s", (claim["attempt_id"],))
        assert ledger.claim_build(claim["run_id"], "builder:recovery", 1) is None
    elif fence == "cancel":
        ledger.cancel_run(claim["run_id"])
    else:
        current = ledger.get_run(claim["run_id"])
        ledger.revise_run(claim["run_id"], current["spec"], 1)
    before = ledger.get_run(claim["run_id"])
    restarted = Ledger(receipt_dsn)
    capture(restarted, grant, "usage")
    capture(restarted, grant, "session_terminal")
    after = restarted.get_run(claim["run_id"])
    assert {key: before[key] for key in ("state", "spent", "reserved", "revision")} == {
        key: after[key] for key in ("state", "spent", "reserved", "revision")}
    receipts = restarted.get_attempt_receipts(claim["run_id"], claim["attempt_id"])
    assert receipts["models"][0]["generation_id"] == event(grant, "generation")["generation_id"]
    assert receipts["models"][0]["usage"]["actual_cost_microdollars"] == 17
    assert receipts["cost_uncertain"] is True and receipts["settles_cost"] is False
    assert receipts["attempt_revision"] == 1
    assert grant["capture_token"] not in json.dumps(receipts)
    with pytest.raises(Conflict):
        capture(restarted, grant, "model_started", model_run="run_1")
    with pytest.raises(Conflict):
        restarted.release_manifest(claim["run_id"])


@pytest.mark.parametrize("pause", ["unknown_cost", "overrun", "unclassified_expiry"])
@pytest.mark.parametrize("new_intent", ["session", "model_started"])
def test_sibling_cost_uncertainty_blocks_fresh_intents_but_allows_late_receipts(
        ledger, receipt_dsn, pause, new_intent):
    first, first_grant = setup(ledger, siblings=True)
    second = ledger.claim_build(first["run_id"], "builder:sibling", 100)
    second_grant = issue_grant(ledger, second)
    start(ledger, first_grant)
    if new_intent == "model_started":
        # An in-progress sibling may still report facts about its first call.
        start(ledger, second_grant)
    if pause == "unclassified_expiry":
        with psycopg.connect(receipt_dsn) as conn:
            conn.execute("UPDATE graphos_attempts SET expires_at=clock_timestamp()-interval '1 second' WHERE id=%s", (first["attempt_id"],))
    else:
        ledger.fail_build(first["run_id"], first["task_id"], first["token"], first["epoch"],
                          "sibling failed", 101 if pause == "overrun" else 0,
                          cost_known=pause == "overrun")
    before = ledger.get_run(first["run_id"])
    assert before["state"] == {"unknown_cost": "RECONCILIATION_REQUIRED",
        "overrun": "BUDGET_EXCEEDED", "unclassified_expiry": "ACTIVE"}[pause]
    if new_intent == "model_started":
        capture(ledger, second_grant, "generation")
        capture(ledger, second_grant, "usage")
    with pytest.raises(Conflict, match="active run|unresolved expired build"):
        capture(ledger, second_grant, new_intent,
                **({"model_run": "run_1"} if new_intent == "model_started" else {}))
    # The failed/expired first call's late receipt is also recovery data only.
    capture(ledger, first_grant, "generation")
    capture(ledger, first_grant, "usage")
    assert capture(ledger, first_grant, "model_started")["duplicate"] is True
    after = ledger.get_run(first["run_id"])
    accounting = ("state", "spent", "reserved", "revision")
    assert {key: before[key] for key in accounting} == {key: after[key] for key in accounting}
    assert after["tasks"] == before["tasks"]
    with psycopg.connect(receipt_dsn) as conn:
        states = dict(conn.execute("SELECT id,state FROM graphos_attempts WHERE id IN (%s,%s)",
                                  (first["attempt_id"], second["attempt_id"])).fetchall())
    assert states[second["attempt_id"]] == "ACTIVE"
    assert states[first["attempt_id"]] == ("ACTIVE" if pause == "unclassified_expiry" else "FAILED")
    receipt = ledger.get_attempt_receipts(first["run_id"], first["attempt_id"])
    assert receipt["models"][0]["usage"]["actual_cost_microdollars"] == 17
    assert receipt["settles_cost"] is False


def test_terminal_session_blocks_new_intents_and_receipt_conflicts(ledger):
    _, grant = setup(ledger)
    start(ledger, grant)
    capture(ledger, grant, "usage")
    capture(ledger, grant, "session_terminal")
    with pytest.raises(Conflict, match="terminal session"):
        capture(ledger, grant, "model_started", model_run="run_1")
    with pytest.raises(Conflict, match="different payload"):
        capture(ledger, grant, "session_terminal", outcome="failed")


def test_completed_lifecycle_after_expired_unknown_generation_never_settles_or_releases(
        ledger, receipt_dsn):
    claim, grant = setup(ledger)
    start(ledger, grant)
    capture(ledger, grant, "generation")
    with psycopg.connect(receipt_dsn) as conn:
        conn.execute("UPDATE graphos_attempts SET expires_at=clock_timestamp()-interval '1 second' WHERE id=%s",
                     (claim["attempt_id"],))
    assert ledger.claim_build(claim["run_id"], "builder:expiry-classification", 100) is None
    before = ledger.get_run(claim["run_id"])
    assert (before["state"], before["spent"], before["reserved"]) == ("RECONCILIATION_REQUIRED", 100, 0)
    assert capture(ledger, grant, "session_terminal")["duplicate"] is False
    assert capture(ledger, grant, "session_terminal")["duplicate"] is True
    for kind in ("generation", "model_started", "session"):
        assert capture(ledger, grant, kind)["duplicate"] is True
    receipts = ledger.get_attempt_receipts(claim["run_id"], claim["attempt_id"])
    assert receipts["capture"]["terminal_outcome"] == "completed"
    assert receipts["models"][0]["usage"] is None
    assert receipts["cost_uncertain"] is True and receipts["settles_cost"] is False
    after = ledger.get_run(claim["run_id"])
    assert {k: before[k] for k in ("state", "spent", "reserved", "tasks")} == {
        k: after[k] for k in ("state", "spent", "reserved", "tasks")}
    assert len(after["uncertain_cost_attempts"]) == 1
    assert after["tasks"][0]["candidate_hash"] is None
    with pytest.raises(Conflict):
        capture(ledger, grant, "model_started", model_run="run_1")
    with pytest.raises(Conflict):
        ledger.release_manifest(claim["run_id"])
    with psycopg.connect(receipt_dsn) as conn:
        assert conn.execute("SELECT count(*) FROM graphos_attempts WHERE task_id=%s",
                            (claim["task_id"],)).fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM graphos_cost_receipts WHERE run_id=%s",
                            (claim["run_id"],)).fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM graphos_releases WHERE run_id=%s",
                            (claim["run_id"],)).fetchone()[0] == 0


def test_three_completed_model_receipts_do_not_authorize_a_fourth(ledger):
    _, grant = setup(ledger)
    capture(ledger, grant, "session")
    for index in range(3):
        run_id = f"run_{index}"
        capture(ledger, grant, "model_started", model_run=run_id)
        usage = event(grant, "usage")["usage"]
        usage["generation_id"] += f"_{index}"
        capture(ledger, grant, "usage", model_run=run_id, usage=usage)
    with pytest.raises(Conflict, match="budget exhausted"):
        capture(ledger, grant, "model_started", model_run="run_3")


def test_usage_cannot_replace_an_early_generation_binding(ledger):
    _, grant = setup(ledger)
    start(ledger, grant)
    capture(ledger, grant, "generation")
    usage = event(grant, "usage")["usage"]
    usage["generation_id"] = "gen_wrong"
    with pytest.raises(Conflict, match="generation identity changed"):
        capture(ledger, grant, "usage", usage=usage)


@pytest.mark.parametrize("order", [
    ("usage", "generation", "session_terminal"),
    ("session_terminal", "usage", "generation"),
    ("generation", "session_terminal", "usage"),
])
def test_reordered_late_facts_preserve_identity_and_do_not_settle(ledger, order):
    claim, grant = setup(ledger)
    start(ledger, grant)
    before = ledger.get_run(claim["run_id"])
    for kind in order:
        assert capture(ledger, grant, kind)["duplicate"] is False
    for kind in reversed(order):
        assert capture(ledger, grant, kind)["duplicate"] is True
    with pytest.raises(Conflict):
        capture(ledger, grant, "generation", generation_id="gen_conflicting_late")
    after = ledger.get_run(claim["run_id"])
    assert {k: before[k] for k in ("spent", "reserved", "state")} == {
        k: after[k] for k in ("spent", "reserved", "state")}
    assert ledger.get_attempt_receipts(claim["run_id"], claim["attempt_id"])["settles_cost"] is False


def test_failure_usage_survives_worker_response_loss_and_restart(ledger, receipt_dsn):
    claim, grant = setup(ledger)
    start(ledger, grant)
    capture(ledger, grant, "usage")
    usage = aggregate(grant)
    fail(ledger, claim, usage)
    restarted = Ledger(receipt_dsn)
    assert fail(restarted, claim, usage)["state"] == "PENDING"
    history = restarted.get_attempt_receipts(claim["run_id"], claim["attempt_id"])
    assert history["failure_usage"] == usage
    current = restarted.get_run(claim["run_id"])
    assert current["spent"] == 17 and current["reserved"] == 0
    assert [item for item in current["events"] if item["kind"] == "BUILD_FAILED"][0]["payload"]["usage"] == usage


@pytest.mark.parametrize("change", [
    lambda usage: usage.update(actual_cost_microdollars=18),
    lambda usage: usage.update(model_runs=0, generations=[]),
    lambda usage: usage.update(input_tokens=True),
    lambda usage: usage.update(private_error="must not be stored"),
    lambda usage: usage["generations"][0].update(run_id="wrong-run"),
    lambda usage: usage["generations"][0].update(generation_id="gen_wrong"),
    lambda usage: usage.update(output_tokens=9),
])
def test_failure_usage_must_match_its_captured_identity_and_totals(ledger, change):
    claim, grant = setup(ledger)
    start(ledger, grant)
    capture(ledger, grant, "usage")
    usage = aggregate(grant)
    change(usage)
    with pytest.raises(Conflict):
        fail(ledger, claim, usage)
    assert ledger.get_run(claim["run_id"])["spent"] == 0


@pytest.mark.parametrize("change", [
    lambda item: item.update(model_attempt=1),
    lambda item: item.update(model_attempt=False),
    lambda item: item.update(private_prompt="never store this"),
    lambda item: item.update(session_id="https://private/token"),
    lambda item: item["usage"].update(actual_cost_microdollars=-1),
    lambda item: item["usage"].update(input_tokens=True),
    lambda item: item["usage"].update(generation_id="https://private/token"),
])
def test_capture_schema_rejects_unsafe_or_unbounded_fields_without_database(change):
    value = event({"session_id": "session_test", "attempt_id": "attempt"}, "usage")
    change(value)
    with pytest.raises(Conflict):
        _receipt_event(value)


def test_api_capture_capability_cannot_read_or_mutate_other_resources(ledger, tmp_path, monkeypatch):
    claim, grant = setup(ledger)
    monkeypatch.setattr("graphos.api.Ledger", lambda _: ledger)
    settings = Settings("postgresql://unused/constructor", tmp_path / "artifacts",
                        "o" * 32, "b" * 32, "v" * 32, allow_fixture=True)
    with TestClient(create_app(settings)) as client:
        path = grant["capture_path"]
        cap = {"Authorization": "Bearer " + grant["capture_token"]}
        assert client.post(path, json=event(grant, "session")).status_code == 401
        assert client.get(path, headers=cap).status_code == 401
        assert client.post(path, headers={"Authorization": "Bearer " + "b" * 32},
                           json=event(grant, "session")).status_code == 403
        created = client.post(path, headers=cap, json=event(grant, "session"))
        assert created.status_code == 200 and created.json()["duplicate"] is False
        assert client.post(path, headers=cap, json=event(grant, "session")).json()["duplicate"] is True
        response = client.get(path, headers={"Authorization": "Bearer " + "o" * 32})
        assert response.status_code == 200 and "token_hash" not in response.text
        assert grant["capture_token"] not in response.text
        grant_path = f"/v1/runs/{claim['run_id']}/tasks/{claim['task_id']}/receipt-grant"
        body = {key: claim[key] for key in ("token", "epoch", "revision", "input_hash")}
        assert client.post(grant_path, headers=cap, json=body).status_code == 401
        for role in ("o", "v"):
            assert client.post(grant_path, headers={"Authorization": "Bearer " + role * 32}, json=body).status_code == 403
        response = client.post(grant_path, headers={"Authorization": "Bearer " + "b" * 32}, json=body)
        assert response.status_code == 200 and response.json()["capture_token"] == grant["capture_token"]
        capture(ledger, grant, "model_started")
        capture(ledger, grant, "usage")
        body = {"token": claim["token"], "epoch": claim["epoch"], "reason": "schema failure",
                "actual_cost": 17, "cost_known": True, "usage": aggregate(grant)}
        response = client.post(f"/v1/runs/{claim['run_id']}/tasks/{claim['task_id']}/fail",
                               headers={"Authorization": "Bearer " + "b" * 32}, json=body)
        assert response.status_code == 200, response.text
        assert client.get(path, headers={"Authorization": "Bearer " + "o" * 32}).json()["failure_usage"] == aggregate(grant)
