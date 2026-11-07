from contextlib import contextmanager
import json
from unittest.mock import Mock

import pytest

from scripts import evaluate_profiles as pilot


def test_disclosed_contract_plan_is_interleaved_and_keeps_all_profiles():
    trials = pilot.planned_trials(list(pilot.PROFILES), 2)
    assert [(t["profile"], t["repeat"]) for t in trials] == [
        (p, repeat) for repeat in (1, 2) for p in pilot.PROFILES]
    assert len({t["id"] for t in trials}) == 6
    assert all(not t["dispatch_started"] for t in trials)


def test_denominator_includes_every_dispatched_failure_and_separates_unattempted():
    trials = pilot.planned_trials(list(pilot.PROFILES), 2)
    for trial, status in zip(trials, ("PASS", "FAIL", "ERROR", "ACCOUNTING_UNKNOWN")):
        trial.update(dispatch_started=True, status=status)
    summary = pilot.live_summary(trials)
    assert summary["overall"] == {"planned": 6, "dispatched": 4, "passed": 1,
        "failed_or_incomplete": 3, "not_dispatched": 2, "observed_pass_fraction": 0.25}
    assert summary["by_profile"]["static-web"]["failed_or_incomplete"] == 1
    assert summary["by_profile"]["local-inventory"]["not_dispatched"] == 1
    assert pilot.live_summary(pilot.planned_trials(["static-web"], 1))["overall"]["observed_pass_fraction"] is None


def test_calibration_cannot_count_infrastructure_failures_as_defect_detection():
    case = {"expected_failed_check": "local_storage_reload"}
    assert not pilot.calibration_matches(case, {"passed": False, "checks": [
        {"name": "sandbox_available", "passed": False}]})
    assert not pilot.calibration_matches(case, {"passed": False, "checks": [
        {"name": "local_storage_reload", "passed": True}]})
    assert pilot.calibration_matches(case, {"passed": False, "checks": [
        {"name": "local_storage_reload", "passed": False}]})
    assert not pilot.calibration_matches({"expected_pass": True}, {"passed": False})


def test_calibration_mutations_never_modify_the_fixture():
    files = {"index.html": "html", "app.js": "code", "styles.css": "style"}
    original = dict(files)
    assert "index.html" not in pilot.calibration_variant(files, "missing-entrypoint")
    assert pilot.calibration_variant(files, "disabled-persistence")["app.js"].startswith("Storage.prototype.setItem")
    assert "#94a3b8" in pilot.calibration_variant(files, "low-contrast-text")["styles.css"]
    assert files == original


@pytest.mark.parametrize("argv", [
    ["live"], ["live", "--execute"],
    ["live", "--execute", "--prior-spend-microdollars", "-1"],
    ["live", "--execute", "--prior-spend-microdollars", "5000000"],
    ["live", "--execute", "--prior-spend-microdollars", "4000001", "--budget", "1000000"],
    ["live", "--execute", "--prior-spend-microdollars", "0", "--budget", "999999"],
    ["live", "--execute", "--prior-spend-microdollars", "0", "--budget", "5000001"],
    ["calibrate", "--profiles", "static-web", "static-web"],
])
def test_dispatch_gate_precedes_services(monkeypatch, argv):
    service = Mock()
    monkeypatch.setattr(pilot, "LiveEve", service)
    with pytest.raises(SystemExit) as result:
        pilot.main(argv)
    assert result.value.code == 2
    service.assert_not_called()


def state(spent=20, name="READY_FOR_RELEASE", uncertain=None, reserved=0):
    return {"state": name, "spent": spent, "reserved": reserved,
            "uncertain_cost_attempts": [] if uncertain is None else uncertain}


@pytest.mark.parametrize("ledger", [{"spent": 0}, state(spent=True), state(spent=-1),
                                       {**state(), "uncertain_cost_attempts": None}])
def test_invalid_accounting_never_implies_free_dispatch(ledger):
    with pytest.raises(ValueError):
        pilot.accounting_state(ledger)


def setup_live(monkeypatch, states, outcomes, *, budget=2_000_000):
    report = {"experiment_id": "unit", "source_digest": "frozen", "budget_microdollars": budget,
              "prior_spend_microdollars": 55_000, "accounted_spend_microdollars": 0,
              "trials": pilot.planned_trials(["static-web"], len(outcomes))}
    states = iter(states)
    posts = Mock(side_effect=lambda *a, **kw: {"id": f"run-{posts.call_count}"})
    @contextmanager
    def client():
        yield Mock(post=posts, get=lambda *a: next(states))
    monkeypatch.setattr(pilot, "client", client)
    monkeypatch.setattr(pilot, "checked", lambda response: response)
    monkeypatch.setattr(pilot, "default_spec", lambda profile: {"profile": profile, "suite_hash": "suite", "policy_hash": "policy"})
    monkeypatch.setattr(pilot, "source_digest", lambda: "frozen")
    attempts = Mock(side_effect=outcomes)
    monkeypatch.setattr(pilot, "run_attempts", attempts)
    return report, attempts, posts


def test_known_generation_or_verification_failure_is_retained_without_retry(monkeypatch):
    report, attempts, posts = setup_live(monkeypatch, [state(name="EXHAUSTED"), state()], [False, True])
    pilot.run_live_trials(report, {}, lambda: None)
    assert report["status"] == "FAIL"
    assert [t["status"] for t in report["trials"]] == ["FAIL", "PASS"]
    assert report["summary"]["overall"]["dispatched"] == 2
    assert report["accounted_spend_microdollars"] == 40
    assert all(call.args[2] == 1 for call in attempts.call_args_list)
    assert all(call.kwargs["json"]["spec"]["max_attempts"] == 1 for call in posts.call_args_list)
    assert posts.call_args_list[0].kwargs["json"]["idempotency_key"] != posts.call_args_list[1].kwargs["json"]["idempotency_key"]


@pytest.mark.parametrize("ledger", [state(1_000_000, "RECONCILIATION_REQUIRED"),
    state(0, reserved=1_000_000), state(0, uncertain=[{"attempt_id": "pending"}])])
def test_uncertain_cost_or_pending_reservation_stops_every_later_trial(monkeypatch, ledger):
    report, attempts, posts = setup_live(monkeypatch, [ledger], [False, True])
    pilot.run_live_trials(report, {}, lambda: None)
    assert report["status"] == "INCOMPLETE"
    assert report["stop_reason"] == "unknown_cost_requires_reconciliation"
    assert report["accounted_spend_microdollars"] == 1_000_000
    assert report["summary"]["overall"]["dispatched"] == 1
    assert report["summary"]["overall"]["not_dispatched"] == 1
    assert attempts.call_count == posts.call_count == 1


def test_interrupted_dispatch_is_not_replaced_and_does_not_leak_raw_exception(monkeypatch):
    report, attempts, posts = setup_live(monkeypatch, [], [RuntimeError("secret-value"), True])
    persisted = []
    pilot.run_live_trials(report, {}, lambda: persisted.append(json.loads(json.dumps(report))))
    assert attempts.call_count == posts.call_count == 1
    assert report["stop_reason"] == "interrupted_dispatch_requires_reconciliation"
    assert report["accounted_spend_microdollars"] == 1_000_000
    assert "secret-value" not in json.dumps(report)
    assert any(r["trials"][0]["dispatch_started"] and r["accounted_spend_microdollars"] == 1_000_000
               for r in persisted)


def test_overspend_stops_global_dispatch(monkeypatch):
    report, attempts, _ = setup_live(monkeypatch, [state(1_000_001, "BUDGET_EXCEEDED")], [False, True])
    pilot.run_live_trials(report, {}, lambda: None)
    assert report["stop_reason"] == "accounting_exceeded_dispatch_budget"
    assert report["accounted_spend_microdollars"] == 1_000_001
    assert attempts.call_count == 1


def test_settled_spend_still_requires_full_next_reservation(monkeypatch):
    report, attempts, _ = setup_live(monkeypatch, [state()], [True, True], budget=1_000_000)
    pilot.run_live_trials(report, {}, lambda: None)
    assert report["stop_reason"] == "insufficient_reservation_headroom"
    assert report["accounted_spend_microdollars"] == 20
    assert attempts.call_count == 1


def test_source_change_prevents_later_dispatch(monkeypatch):
    report, attempts, _ = setup_live(monkeypatch, [state()], [True, True])
    monkeypatch.setattr(pilot, "source_digest", Mock(side_effect=["frozen", "changed"]))
    pilot.run_live_trials(report, {}, lambda: None)
    assert report["stop_reason"] == "source_changed"
    assert attempts.call_count == 1


def test_calibration_is_separate_and_continues_after_grader_errors(monkeypatch):
    protocol = json.loads(pilot.PROTOCOL_PATH.read_text())
    report = {"profiles": list(pilot.PROFILES), "protocol": protocol}
    monkeypatch.setattr(pilot, "get_profile", lambda name: {"suite_hash": "s", "policy_hash": "p", "acceptance_criteria": ["contract"]})
    monkeypatch.setattr(pilot, "fixture_files", lambda name: {"index.html": "html", "app.js": "code", "styles.css": "css"})
    verifier = Mock(side_effect=RuntimeError("private-verifier-log"))
    model = Mock()
    monkeypatch.setattr(pilot, "verify_bundle", verifier)
    monkeypatch.setattr(pilot, "LiveEve", model)
    pilot.run_calibration(report, lambda: None)
    assert report["status"] == "FAIL"
    assert verifier.call_count == 3 * len(protocol["calibration_cases"])
    assert report["summary"]["expected_behavior_observed"] == 0
    assert "private-verifier-log" not in json.dumps(report)
    assert {call.kwargs["profile_id"] for call in verifier.call_args_list} == set(pilot.PROFILES)
    model.assert_not_called()


def test_existing_evidence_cannot_be_overwritten(monkeypatch, tmp_path):
    output = tmp_path / "existing.json"
    output.write_text("prior evidence")
    service = Mock()
    monkeypatch.setattr(pilot, "LiveEve", service)
    with pytest.raises(SystemExit):
        pilot.main(["calibrate", "--output", str(output)])
    assert output.read_text() == "prior evidence"
    service.assert_not_called()
