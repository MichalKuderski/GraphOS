"""No-model tests for exact historical-candidate replay and bounded repair."""
from copy import deepcopy
from contextlib import contextmanager
import json
import os
from unittest.mock import Mock

import pytest

from scripts import repair_replay as replay

FILES = {"index.html": "<main>tasks</main>", "app.js": "// original app", "styles.css": "body{}"}
CANDIDATE = replay.bundle_digest(FILES)
HASH = "a" * 64


def source_data():
    identity = {"attempt_id": "verify-old", "candidate_hash": CANDIDATE,
                "input_hash": HASH, "suite_hash": HASH, "policy_hash": HASH}
    verification = {**identity, "revision": 1, "evidence_hash": HASH, "passed": False}
    provenance = {"mode": "eve", "model": "model", "session_id": "session-old", "request_sha256": HASH}
    source = {"run_id": "original-run", "status": "FAIL", "attempts": [{
        "passed": False, "build_status": "submitted", "verification_identity": identity,
        "build_identity": {"attempt_id": "build-old", "task_id": "task-old", "revision": 1}}]}
    state = {"id": "original-run", "revision": 1, "state": "EXHAUSTED", "spent": 123,
             "reserved": 0, "uncertain_cost_attempts": [],
             "spec": {"profile": "static-web", "suite_hash": HASH, "policy_hash": HASH},
             "tasks": [{"id": "task-old", "candidate_hash": CANDIDATE, "input_hash": HASH,
                        "evidence_hash": HASH, "verification": verification}],
             "events": [{"kind": "BUILD_SUBMITTED", "revision": 1, "payload": {
                 "task_id": "task-old", "attempt_id": "build-old", "candidate_hash": CANDIDATE,
                 "provenance": provenance}}]}
    artifact = {"manifest_hash": CANDIDATE, "files": dict(FILES)}
    return source, state, artifact


def context():
    binding = {"candidate_hash": CANDIDATE, "evidence_hash": HASH, "verifier_attempt_id": "verify-current",
               "input_hash": HASH, "revision": 1, "suite_hash": HASH, "policy_hash": HASH,
               "failed_checks": ["visible_focus"]}
    repair = {**{k: binding[k] for k in replay.BINDINGS}, "files": dict(FILES),
              "checks": [{"name": "visible_focus", "passed": False, "detail": "No focus change"}]}
    claim = {"repair": deepcopy({k: v for k, v in repair.items() if k != "files"})}
    return binding, repair, claim


def experiment():
    return {"run_id": "new-run", "experiment_id": "unit", "source_digest": "frozen",
            "max_live_repairs": 2, "live_builds_dispatched": 0, "attempts": [],
            "budget_microdollars": 2_000_000, "prior_spend_microdollars": 347_268,
            "accounted_spend_microdollars": 0, "seed": {"source_candidate_hash": CANDIDATE}}


def test_exact_seed_has_authoritative_origin_and_zero_new_generation_attribution():
    source, state, artifact = source_data()
    before = deepcopy((source, state, artifact))
    binding, files, original = replay.validate_seed(source, state, artifact, CANDIDATE)
    assert files == FILES
    assert binding["source_build_attempt_id"] == "build-old"
    assert binding["source_verifier_attempt_id"] == "verify-old"
    assert binding["source_run_spent_microdollars"] == 123
    provenance = replay.replay_provenance(binding, original)
    assert provenance["mode"] == "eve"
    assert provenance["operation"] == "immutable-candidate-replay"
    assert provenance["generation_performed"] is False
    assert provenance["new_model_cost_microdollars"] == 0
    assert provenance["original_provenance"] == original
    assert (source, state, artifact) == before


@pytest.mark.parametrize("change", [
    lambda source, state, artifact: source.update(run_id="another-run"),
    lambda source, state, artifact: source.update(status="PASS"),
    lambda source, state, artifact: source["attempts"][-1].update(passed=True),
    lambda source, state, artifact: state.update(state="ACTIVE"),
    lambda source, state, artifact: state.update(reserved=1),
    lambda source, state, artifact: state.update(uncertain_cost_attempts=[{"attempt_id": "pending"}]),
    lambda source, state, artifact: state["tasks"][0].update(candidate_hash=HASH),
    lambda source, state, artifact: state["tasks"][0]["verification"].update(attempt_id="different-verifier"),
    lambda source, state, artifact: state["tasks"][0]["verification"].update(revision=2),
    lambda source, state, artifact: state["tasks"][0]["verification"].update(evidence_hash="b" * 64),
    lambda source, state, artifact: state["events"][0]["payload"].update(attempt_id="different-build"),
    lambda source, state, artifact: state["events"][0]["payload"]["provenance"].update(mode="fixture"),
    lambda source, state, artifact: state["events"][0]["payload"]["provenance"].update(generation_performed=False),
    lambda source, state, artifact: artifact["files"].update({"app.js": "// patched manually"}),
])
def test_seed_rejects_wrong_origins_uncertain_spend_and_changed_bytes(change):
    source, state, artifact = source_data()
    change(source, state, artifact)
    with pytest.raises(ValueError):
        replay.validate_seed(source, state, artifact, CANDIDATE)


def test_guard_forwards_scoped_receipt_and_real_adapter_result_once(monkeypatch):
    monkeypatch.setattr(replay, "source_digest", lambda: "frozen")
    binding, repair, claim = context()
    report, attempt = experiment(), {}
    result = {"real_adapter_output": True}
    original, persist = Mock(return_value=result), Mock()
    guard = replay.guarded_adapter(original, binding, report, attempt, persist)
    receipt = {"token": "private-grant", "id": "grant"}
    assert guard(claim, {}, [], repair, receipt=receipt) is result
    original.assert_called_once_with(claim, {}, [], repair, receipt=receipt)
    assert report["live_builds_dispatched"] == 1
    assert attempt["repair_bindings_checked"] is True
    assert "private-grant" not in json.dumps(attempt)
    with pytest.raises(replay.worker.BuildFailure) as error:
        guard(claim, {}, [], repair, receipt=receipt)
    assert error.value.actual_cost == 0
    assert original.call_count == 1


@pytest.mark.parametrize("change", [
    lambda binding, repair, claim, report: repair.update(evidence_hash="b" * 64),
    lambda binding, repair, claim, report: repair["files"].update({"app.js": "// substituted"}),
    lambda binding, repair, claim, report: repair.update(checks=[{"name": "different_check", "passed": False}]),
    lambda binding, repair, claim, report: repair["checks"][0].update(detail="substituted diagnostics"),
    lambda binding, repair, claim, report: claim["repair"].update(verifier_attempt_id="stale"),
    lambda binding, repair, claim, report: report.update(live_builds_dispatched=2),
    lambda binding, repair, claim, report: report.update(source_digest="changed"),
])
def test_guard_rejects_unbound_or_excess_dispatch_before_payment(monkeypatch, change):
    monkeypatch.setattr(replay, "source_digest", lambda: "frozen")
    binding, repair, claim = context()
    report = experiment()
    change(binding, repair, claim, report)
    original = Mock()
    with pytest.raises(replay.worker.BuildFailure) as error:
        replay.guarded_adapter(original, binding, report, {}, Mock())(claim, {}, [], repair)
    assert error.value.actual_cost == 0
    original.assert_not_called()


def current_rejection():
    binding, repair, _ = context()
    claim = {k: binding[k] for k in ("candidate_hash", "input_hash", "revision", "suite_hash", "policy_hash")}
    claim["attempt_id"] = binding["verifier_attempt_id"]
    checks = repair["checks"]
    result = {"status": "verified", "passed": False, "claim": claim,
              "report": {"passed": False, "checks": checks, "suite_hash": HASH, "policy_hash": HASH}}
    task = {"candidate_hash": CANDIDATE, "evidence_hash": HASH,
            "verification": {**claim, "evidence_hash": HASH, "passed": False}}
    state = {"tasks": [task]}
    profile = {"required_checks": ["visible_focus"], "suite_hash": HASH, "policy_hash": HASH}
    return result, state, profile


def test_current_full_suite_rejection_is_required_before_paid_repair():
    result, state, profile = current_rejection()
    assert replay.rejected_binding(result, state, profile)["failed_checks"] == ["visible_focus"]
    for altered in ({**result, "status": "failed"}, {**result, "passed": True},
                    {**result, "report": {"passed": False, "checks": [{"name": "sandbox_available", "passed": False}]}}):
        with pytest.raises(ValueError):
            replay.rejected_binding(altered, state, profile)


def ledger_state(name="ACTIVE", spent=0, uncertain=False):
    return {"state": name, "spent": spent, "reserved": 0,
            "uncertain_cost_attempts": [{"attempt_id": "pending"}] if uncertain else []}


def test_uncertain_cost_stops_and_keeps_reservation_without_verification(monkeypatch):
    report = experiment()
    monkeypatch.setattr(replay, "read_state", Mock(side_effect=[ledger_state(), ledger_state("RECONCILIATION_REQUIRED", 1_000_000, True)]))
    build, verify = Mock(return_value={"status": "failed"}), Mock()
    monkeypatch.setattr(replay.worker, "build_once", build)
    monkeypatch.setattr(replay.worker, "verify_once", verify)
    replay.run_repairs(report, {"GRAPHOS_API_URL": "url", "GRAPHOS_BUILDER_TOKEN": "private"}, context()[0], {}, Mock())
    assert report["status"] == "INCOMPLETE"
    assert report["accounted_spend_microdollars"] == 1_000_000
    assert len(report["attempts"]) == build.call_count == 1
    verify.assert_not_called()


def test_settled_build_failure_is_not_automatically_retried(monkeypatch):
    report = experiment()
    monkeypatch.setattr(replay, "read_state", Mock(side_effect=[ledger_state(), ledger_state(spent=120)]))
    build = Mock(return_value={"status": "failed", "reason": "sanitized failure"})
    monkeypatch.setattr(replay.worker, "build_once", build)
    replay.run_repairs(report, {"GRAPHOS_API_URL": "url", "GRAPHOS_BUILDER_TOKEN": "private"}, context()[0], {}, Mock())
    assert report["status"] == "FAIL"
    assert report["spent_microdollars"] == 120
    assert build.call_count == 1


def test_uncertain_later_repair_preserves_spend_plus_live_reservation(monkeypatch):
    report = experiment()
    prior = ledger_state(spent=10_000)
    unresolved = {**prior, "reserved": 1_000_000}
    monkeypatch.setattr(replay, "read_state", Mock(side_effect=[prior, unresolved]))
    monkeypatch.setattr(replay.worker, "build_once", Mock(return_value={"status": "failed"}))
    verify = Mock()
    monkeypatch.setattr(replay.worker, "verify_once", verify)
    replay.run_repairs(report, {"GRAPHOS_API_URL": "url", "GRAPHOS_BUILDER_TOKEN": "private"},
                       context()[0], {}, Mock())
    assert report["status"] == "INCOMPLETE"
    assert report["accounted_spend_microdollars"] == 1_010_000
    assert report["stop_reason"] == "accounting_requires_reconciliation"
    verify.assert_not_called()


def test_budget_headroom_gate_precedes_claim(monkeypatch):
    report = experiment()
    report["budget_microdollars"] = 1_000_000
    monkeypatch.setattr(replay, "read_state", Mock(return_value=ledger_state(spent=1)))
    build = Mock()
    monkeypatch.setattr(replay.worker, "build_once", build)
    replay.run_repairs(report, {}, context()[0], {}, Mock())
    assert report["stop_reason"] == "insufficient_reservation_headroom"
    build.assert_not_called()


@pytest.mark.parametrize("boundary", ["before_dispatch", "after_verification"])
def test_every_state_boundary_retains_unsettled_exposure(monkeypatch, boundary):
    report = experiment()
    unsettled = {**ledger_state(spent=10_000), "reserved": 1_000_000}
    snapshots = [unsettled] if boundary == "before_dispatch" else [ledger_state(), ledger_state(spent=10_000), unsettled]
    monkeypatch.setattr(replay, "read_state", Mock(side_effect=snapshots))
    build = Mock(return_value={"status": "submitted"})
    monkeypatch.setattr(replay.worker, "build_once", build)
    monkeypatch.setattr(replay.worker, "verify_once", Mock(return_value={"status": "verified", "passed": False}))
    export = Mock()
    monkeypatch.setattr(replay, "export_release", export)
    replay.run_repairs(report, {"GRAPHOS_API_URL": "url", "GRAPHOS_BUILDER_TOKEN": "private",
                               "GRAPHOS_VERIFIER_TOKEN": "private-verifier"}, context()[0], {}, Mock())
    assert report["status"] == "INCOMPLETE"
    assert report["accounted_spend_microdollars"] == 1_010_000
    assert report["accounting_reconciliation_required"] is True
    if boundary == "before_dispatch":
        build.assert_not_called()
    export.assert_not_called()


@pytest.mark.parametrize("changed,actually_dispatched", [(False, True), (True, False), (True, True)])
def test_export_requires_distinct_real_repair_and_fresh_verification(monkeypatch, changed, actually_dispatched):
    report = experiment()
    binding, repair, claim = context()
    monkeypatch.setattr(replay, "source_digest", lambda: "frozen")
    monkeypatch.setattr(replay, "read_state", Mock(side_effect=[ledger_state(), ledger_state(spent=20), ledger_state("READY_FOR_RELEASE", 20)]))
    original = Mock(return_value={"files": {**FILES, "app.js": "// actual repaired app"}})
    monkeypatch.setattr(replay.worker, "_eve_build", original)
    def build(*args, **kwargs):
        if actually_dispatched:
            replay.worker._eve_build(claim, {}, [], repair, receipt={"token": "private-grant"})
        return {"status": "submitted"}
    monkeypatch.setattr(replay.worker, "build_once", build)
    monkeypatch.setattr(replay.worker, "verify_once", Mock(return_value={"status": "verified", "passed": True,
                         "claim": {"candidate_hash": HASH if changed else CANDIDATE}}))
    export = Mock(return_value={"manifest_hash": HASH})
    monkeypatch.setattr(replay, "export_release", export)
    env = {"GRAPHOS_API_URL": "url", "GRAPHOS_BUILDER_TOKEN": "builder", "GRAPHOS_VERIFIER_TOKEN": "verifier"}
    replay.run_repairs(report, env, binding, {}, Mock())
    if changed and actually_dispatched:
        assert report["status"] == "PASS"
        export.assert_called_once()
    else:
        assert report["status"] == "INCOMPLETE"
        export.assert_not_called()


@pytest.mark.parametrize("extra", [[], ["--execute", "--prior-spend-microdollars", "-1"],
    ["--execute", "--prior-spend-microdollars", "4000000", "--budget", "2000000"],
    ["--execute", "--prior-spend-microdollars", "0", "--max-repairs", "3"]])
def test_cli_rejects_unapproved_or_overbudget_dispatch_before_services(monkeypatch, extra):
    service = Mock()
    monkeypatch.setattr(replay, "ManagedAPI", service)
    with pytest.raises(SystemExit):
        replay.main(["missing-source.json", "--candidate-hash", CANDIDATE, *extra])
    service.assert_not_called()


def test_seed_that_passes_current_suite_never_starts_model_or_exports(monkeypatch, tmp_path):
    source, state, artifact = source_data()
    path = tmp_path / "source.json"
    output = tmp_path / "replay.json"
    path.write_text(json.dumps(source))
    api = Mock(url="http://127.0.0.1:12345")
    eve, export, importer = Mock(), Mock(), Mock()
    monkeypatch.setattr(replay, "ManagedAPI", Mock(return_value=api))
    monkeypatch.setattr(replay, "LiveEve", eve)
    monkeypatch.setattr(replay, "export_release", export)
    monkeypatch.setattr(replay, "import_seed", importer)
    monkeypatch.setattr(replay, "source_digest", lambda: "frozen")
    monkeypatch.setattr(replay, "local_environment", lambda: {"GRAPHOS_VERIFIER_TOKEN": "private"})
    monkeypatch.setattr(replay, "read_state", lambda run_id: state)
    monkeypatch.setattr(replay, "get_profile", lambda name: {})
    monkeypatch.setattr(replay, "default_spec", lambda name: {"suite_hash": HASH, "policy_hash": HASH})
    monkeypatch.setattr(replay.worker, "verify_once", Mock(return_value={"status": "verified", "passed": True, "claim": {"candidate_hash": CANDIDATE}}))
    @contextmanager
    def client():
        yield Mock(get=lambda path: artifact, post=lambda *a, **kw: {"id": "new-run"})
    monkeypatch.setattr(replay, "client", client)
    monkeypatch.setattr(replay, "checked", lambda response: response)
    previous_env = os.environ.copy()
    assert replay.main([str(path), "--candidate-hash", CANDIDATE, "--execute",
                        "--prior-spend-microdollars", "347268", "--output", str(output)]) == 1
    result = json.loads(output.read_text())
    assert result["status"] == "SEED_ALREADY_PASSES"
    assert result["live_builds_dispatched"] == 0
    assert result["seed_import_is_model_generation"] is False
    assert importer.call_args.args[1] == FILES
    assert importer.call_args.args[2]["generation_performed"] is False
    eve.assert_not_called()
    export.assert_not_called()
    api.close.assert_called_once()
    assert os.environ == previous_env
