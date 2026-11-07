"""Fixture grader calibration and an explicit, serial disclosed-contract model pilot.

Calibration spends no model tokens. Live mode never repairs, replaces, or resumes a
trial and requires independently reconciled prior session spending. Provider
budgets are soft; the reservation gate controls dispatch, not the final invoice.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from graphos.__main__ import checked, client  # noqa: E402
from graphos.profiles import default_spec, fixture_files, get_profile  # noqa: E402
from graphos.sandbox import verify_bundle  # noqa: E402
from scripts.acceptance import ManagedAPI, local_environment  # noqa: E402
from scripts.check import source_digest  # noqa: E402
from scripts.live_acceptance import LiveEve, control_environment, now, run_attempts, save  # noqa: E402

PROTOCOL_PATH = ROOT / "evals/pilot-protocol.json"
PROFILES = ("static-web", "local-notes", "local-inventory")
SESSION_CAP = 5_000_000
RESERVATION = 1_000_000


def planned_trials(profiles: list[str], repeats: int) -> list[dict]:
    return [{"id": f"{profile}-{repeat}", "profile": profile, "repeat": repeat,
             "status": "NOT_DISPATCHED", "dispatch_started": False, "attempts": []}
            for repeat in range(1, repeats + 1) for profile in profiles]


def live_summary(trials: list[dict]) -> dict:
    """All dispatched trials remain in the denominator, irrespective of outcome."""
    def counts(items):
        attempted = sum(t["dispatch_started"] for t in items)
        passed = sum(t["dispatch_started"] and t["status"] == "PASS" for t in items)
        return {"planned": len(items), "dispatched": attempted, "passed": passed,
                "failed_or_incomplete": attempted - passed,
                "not_dispatched": len(items) - attempted,
                "observed_pass_fraction": passed / attempted if attempted else None}
    return {"overall": counts(trials),
            "by_profile": {name: counts([t for t in trials if t["profile"] == name])
                           for name in dict.fromkeys(t["profile"] for t in trials)}}


def calibration_variant(files: dict[str, str], case: str) -> dict[str, str]:
    result = dict(files)
    if case == "missing-entrypoint":
        result.pop("index.html")
    elif case == "disabled-persistence":
        result["app.js"] = "Storage.prototype.setItem = function () {};\n" + result["app.js"]
    elif case == "low-contrast-text":
        result["styles.css"] += ("\nbody, body * { color: #94a3b8 !important; "
                                 "background-color: #f8fafc !important; }\n")
    elif case != "positive-fixture":
        raise ValueError("unknown calibration case")
    return result


def calibration_matches(case: dict, result: dict) -> bool:
    if case.get("expected_pass") is True:
        return result.get("passed") is True
    # An unrelated infrastructure error must not count as detecting a defect.
    return result.get("passed") is False and any(
        check.get("name") == case["expected_failed_check"] and check.get("passed") is False
        for check in result.get("checks", []))


def run_calibration(report: dict, persist) -> None:
    cases = report["protocol"]["calibration_cases"]
    report["cases"] = []
    for profile_id in report["profiles"]:
        profile = get_profile(profile_id)
        files = fixture_files(profile_id)
        for case in cases:
            entry = {"profile": profile_id, "case": case["id"], "kind": case["kind"],
                     "status": "RUNNING", "suite_hash": profile["suite_hash"],
                     "policy_hash": profile["policy_hash"]}
            report["cases"].append(entry)
            persist()
            try:
                result = verify_bundle(calibration_variant(files, case["id"]),
                                       profile["acceptance_criteria"], profile_id=profile_id)
                entry.update(report=result, expected_behavior_observed=calibration_matches(case, result),
                             status="COMPLETE")
            except Exception as exc:
                # Retain the case. Never put arbitrary exception text into public evidence.
                entry.update(status="ERROR", error_type=type(exc).__name__, expected_behavior_observed=False)
            persist()
    report["summary"] = {
        "cases": len(report["cases"]),
        "expected_behavior_observed": sum(c["expected_behavior_observed"] for c in report["cases"]),
        "by_profile": {name: {"cases": sum(c["profile"] == name for c in report["cases"]),
                              "expected_behavior_observed": sum(c["profile"] == name and c["expected_behavior_observed"]
                                                                for c in report["cases"])}
                       for name in report["profiles"]},
        "measures": "Grader sensitivity on declared fixtures and injected faults, not model performance"}
    report["status"] = "PASS" if all(c["expected_behavior_observed"] for c in report["cases"]) else "FAIL"


def accounting_state(state: dict) -> tuple[int, bool]:
    spent = state.get("spent")
    reserved = state.get("reserved")
    if type(spent) is not int or spent < 0 or type(reserved) is not int or reserved < 0:
        raise ValueError("invalid ledger accounting")
    uncertain = state.get("uncertain_cost_attempts")
    # Missing accounting evidence is unknown, never implicitly a zero-cost run.
    if not isinstance(uncertain, list):
        raise ValueError("missing reconciliation evidence")
    return spent, bool(uncertain) or reserved > 0 or state["state"] == "RECONCILIATION_REQUIRED"


def run_live_trials(report: dict, env: dict, persist) -> None:
    """Services are already started. Never re-dispatch a trial with unknown cost."""
    accounted = 0
    for trial in report["trials"]:
        if source_digest() != report["source_digest"]:
            report["stop_reason"] = "source_changed"
            break
        if (accounted + RESERVATION > report["budget_microdollars"] or
                report["prior_spend_microdollars"] + accounted + RESERVATION > SESSION_CAP):
            report["stop_reason"] = "insufficient_reservation_headroom"
            break
        trial["started_at"] = now()
        trial["status"] = "CREATING_RUN"
        persist()
        try:
            spec = default_spec(trial["profile"])
            spec.update(name=f"Disclosed-contract pilot: {trial['id']}", max_attempts=1)
            trial.update(suite_hash=spec["suite_hash"], policy_hash=spec["policy_hash"])
            with client() as http:
                run = checked(http.post("/v1/runs", json={"spec": spec, "budget": RESERVATION,
                    "idempotency_key": f"pilot-{report['experiment_id']}-{trial['id']}"}))
            trial["run_id"] = str(run["id"])
            trial.update(dispatch_started=True, status="DISPATCHED", cost_status="UNKNOWN")
            # Save the reservation before calling any paid provider operation.
            report["accounted_spend_microdollars"] = accounted + RESERVATION
            persist()
            accepted = run_attempts(trial["run_id"], env, 1, trial, persist)
            with client() as http:
                state = checked(http.get(f"/v1/runs/{trial['run_id']}"))
            spent, uncertain = accounting_state(state)
            if uncertain:
                accounted += max(spent, RESERVATION)
                trial.update(status="ACCOUNTING_UNKNOWN", cost_status="UNKNOWN",
                             accounted_microdollars=max(spent, RESERVATION))
                report["stop_reason"] = "unknown_cost_requires_reconciliation"
            else:
                accounted += spent
                trial.update(status="PASS" if accepted else "FAIL", cost_status="SETTLED",
                             accounted_microdollars=spent, spent_microdollars=spent)
                if (state["state"] == "BUDGET_EXCEEDED" or spent > RESERVATION or
                        accounted > report["budget_microdollars"] or
                        report["prior_spend_microdollars"] + accounted > SESSION_CAP):
                    report["stop_reason"] = "accounting_exceeded_dispatch_budget"
            report["accounted_spend_microdollars"] = accounted
        except Exception as exc:
            trial.update(status="ERROR", error_type=type(exc).__name__)
            if trial["dispatch_started"]:
                accounted += RESERVATION
                trial.update(cost_status="UNKNOWN", accounted_microdollars=RESERVATION)
                report["accounted_spend_microdollars"] = accounted
                report["stop_reason"] = "interrupted_dispatch_requires_reconciliation"
            else:
                report["stop_reason"] = "trial_setup_failed"
        finally:
            trial["finished_at"] = now()
            report["summary"] = live_summary(report["trials"])
            persist()
        if report.get("stop_reason"):
            break
    report["summary"] = live_summary(report["trials"])
    report["status"] = ("INCOMPLETE" if report.get("stop_reason") else
                        "PASS" if report["summary"]["overall"]["failed_or_incomplete"] == 0 else "FAIL")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("calibrate", "live"))
    parser.add_argument("--profiles", nargs="+", choices=PROFILES, default=list(PROFILES))
    parser.add_argument("--trials", type=int, choices=range(1, 21), default=2)
    parser.add_argument("--execute", action="store_true", help="Allow paid model dispatch in live mode")
    parser.add_argument("--prior-spend-microdollars", type=int, default=None,
                        help="Independently reconciled spend across this entire authorized session, rounded up")
    parser.add_argument("--budget", type=int, default=2_000_000,
                        help="Pilot accounting cap in microdollars, including pending reservations")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if len(args.profiles) != len(set(args.profiles)):
        parser.error("profiles must not repeat; use --trials for repeated generations")
    if args.mode == "live":
        if not args.execute:
            parser.error("live mode requires --execute; real model requests incur charges")
        if args.prior_spend_microdollars is None or not 0 <= args.prior_spend_microdollars < SESSION_CAP:
            parser.error("live mode requires valid --prior-spend-microdollars from independent reconciliation")
        if not RESERVATION <= args.budget <= SESSION_CAP - args.prior_spend_microdollars:
            parser.error("pilot budget must fund one reservation and fit the remaining $5 session authorization")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]
    output = args.output or ROOT / "evals/results" / f"profile-{args.mode}-{stamp}.json"
    if output.exists():
        parser.error("output already exists; retain every previous trial and never silently resume it")
    protocol = json.loads(PROTOCOL_PATH.read_text())
    report = {"schema_version": 1, "experiment_id": stamp, "mode": args.mode,
              "status": "RUNNING", "started_at": now(), "source_digest": source_digest(),
              "profiles": args.profiles, "protocol": protocol,
              "evaluation_class": "fixture-grader-calibration" if args.mode == "calibrate" else "disclosed-contract-live-pilot",
              "held_out": False, "production_certification": False}
    if args.mode == "live":
        report.update(trials=planned_trials(args.profiles, args.trials),
                      prior_spend_microdollars=args.prior_spend_microdollars,
                      budget_microdollars=args.budget, attempt_reservation_microdollars=RESERVATION,
                      accounted_spend_microdollars=0, gateway_budget_is_soft=True)
    def persist():
        save(output, report)
    persist()
    previous = os.environ.copy()
    eve = api = None
    try:
        env = local_environment()
        controller_env = control_environment(env)
        controller_env["GRAPHOS_ALLOW_FIXTURE"] = "0"
        os.environ.clear()
        os.environ.update(controller_env)
        if args.mode == "calibrate":
            run_calibration(report, persist)
        else:
            # Credentials are isolated by the existing bounded live acceptance helpers.
            eve = LiveEve(env)
            api = ManagedAPI(controller_env)
            eve.build()
            if source_digest() != report["source_digest"]:
                raise RuntimeError("source_changed_during_build")
            report["compiled_from_current_source"] = True
            persist()
            api.start()
            eve.start()
            execution_env = {**controller_env, "GRAPHOS_API_URL": api.url, "EVE_SERVER_URL": eve.url}
            os.environ.clear()
            os.environ.update(execution_env)
            run_live_trials(report, execution_env, persist)
    except Exception as exc:
        report.update(status="ERROR", error_type=type(exc).__name__)
    finally:
        try:
            if eve:
                eve.close()
        finally:
            try:
                if api:
                    api.close()
            finally:
                os.environ.clear()
                os.environ.update(previous)
                report.update(finished_at=now(), source_unchanged=source_digest() == report["source_digest"])
                if report["status"] == "RUNNING":
                    report["status"] = "INTERRUPTED"
                if not report["source_unchanged"]:
                    report["status"] = "INCOMPLETE"
                if args.mode == "live":
                    report["summary"] = live_summary(report["trials"])
                    report["settled_spend_microdollars"] = sum(
                        t["accounted_microdollars"] for t in report["trials"] if t.get("cost_status") == "SETTLED")
                    report["session_accounted_microdollars"] = (report["prior_spend_microdollars"] +
                                                               report["accounted_spend_microdollars"])
                persist()
    print(json.dumps({"status": report["status"], "mode": args.mode, "result": str(output),
                      "summary": report.get("summary"), "production_certification": False}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
