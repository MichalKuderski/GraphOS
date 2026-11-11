"""Replay an exact rejected AI candidate, then perform bounded evidence-bound repairs.

The imported seed is not a new generation and incurs zero new model cost. Old
runs and reports remain unchanged. Only a distinct, genuinely generated repair
that passes the current trusted suite can be exported. This is an exploratory
repair experiment, separate from first-attempt model evaluations.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from graphos import worker  # noqa: E402
from graphos.__main__ import checked, client, export_release  # noqa: E402
from graphos.artifacts import bundle_digest, canonical, validate_digest, validate_files  # noqa: E402
from graphos.profiles import default_spec, get_profile  # noqa: E402
from scripts.check import source_digest  # noqa: E402
from scripts.controlled_repair import summarize_build  # noqa: E402
from scripts.evaluate_profiles import accounting_state, RESERVATION, SESSION_CAP  # noqa: E402
from scripts.live_acceptance import LiveEve, ManagedAPI, control_environment, local_environment, now, save  # noqa: E402

BINDINGS = ("candidate_hash", "evidence_hash", "verifier_attempt_id", "input_hash",
            "revision", "suite_hash", "policy_hash")


def digest(value: dict) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def read_state(run_id: str) -> dict:
    with client() as http:
        return checked(http.get(f"/v1/runs/{run_id}"))


def validate_seed(source: dict, state: dict, artifact: dict, expected_hash: str) -> tuple[dict, dict, dict]:
    """Bind the report to the authoritative last rejection and original live build."""
    validate_digest(expected_hash)
    spent, uncertain = accounting_state(state)
    if uncertain or state.get("state") != "EXHAUSTED":
        raise ValueError("source_run_must_be_exhausted_and_settled")
    if source.get("run_id") != str(state.get("id")) or source.get("status") != "FAIL":
        raise ValueError("source_report_run_mismatch")
    attempts = source.get("attempts", [])
    if not attempts or attempts[-1].get("passed") is not False or attempts[-1].get("build_status") != "submitted":
        raise ValueError("source_report_requires_last_rejected_candidate")
    attempt = attempts[-1]
    tasks = state.get("tasks", [])
    if len(tasks) != 1:
        raise ValueError("source_must_have_one_task")
    task = tasks[0]
    record = task.get("verification") or {}
    build_identity = attempt.get("build_identity") or {}
    identity = attempt.get("verification_identity") or {}
    if (task.get("candidate_hash") != expected_hash or record.get("candidate_hash") != expected_hash
            or identity.get("candidate_hash") != expected_hash or record.get("passed") is not False
            or record.get("attempt_id") != identity.get("attempt_id")
            or str(task.get("id")) != build_identity.get("task_id")
            or record.get("revision") != state.get("revision")
            or build_identity.get("revision") != state.get("revision")
            or any(record.get(k) != identity.get(k) for k in ("input_hash", "suite_hash", "policy_hash"))
            or record.get("evidence_hash") != task.get("evidence_hash")):
        raise ValueError("source_rejection_binding_mismatch")
    if (record.get("input_hash") != task.get("input_hash")
            or record.get("suite_hash") != state["spec"]["suite_hash"]
            or record.get("policy_hash") != state["spec"]["policy_hash"]):
        raise ValueError("source_rejection_spec_mismatch")
    events = [e for e in state.get("events", []) if e.get("kind") == "BUILD_SUBMITTED"
              and e.get("revision") == state["revision"]
              and e.get("payload", {}).get("task_id") == str(task["id"])]
    if not events:
        raise ValueError("source_live_build_missing")
    build = events[-1]["payload"]
    provenance = build.get("provenance") or {}
    if (build.get("candidate_hash") != expected_hash
            or build.get("attempt_id") != build_identity.get("attempt_id")
            or provenance.get("mode") != "eve" or provenance.get("generation_performed") is False
            or provenance.get("operation") == "immutable-candidate-replay"
            or not provenance.get("session_id") or not provenance.get("model")):
        raise ValueError("source_must_be_original_live_generation")
    if artifact.get("manifest_hash") != expected_hash or bundle_digest(artifact.get("files")) != expected_hash:
        raise ValueError("source_artifact_hash_mismatch")
    files = artifact["files"]
    validate_files(files)
    binding = {"source_run_id": str(state["id"]), "source_revision": state["revision"],
               "source_profile": state["spec"]["profile"], "source_task_id": str(task["id"]),
               "source_build_attempt_id": build["attempt_id"],
               "source_verifier_attempt_id": record["attempt_id"],
               "source_candidate_hash": expected_hash, "source_evidence_hash": record["evidence_hash"],
               "source_input_hash": record["input_hash"], "source_suite_hash": record["suite_hash"],
               "source_policy_hash": record["policy_hash"], "source_run_spent_microdollars": spent,
               "original_provenance_sha256": digest(provenance)}
    return binding, dict(files), provenance


def replay_provenance(binding: dict, original: dict) -> dict:
    # mode identifies the proven AI origin; operation and generation_performed
    # explicitly prevent counting this zero-cost byte import as a model call.
    return {"mode": "eve", "operation": "immutable-candidate-replay", "generation_performed": False,
            "new_model_cost_microdollars": 0, **binding, "original_provenance": original}


def rejected_binding(verified: dict, state: dict, profile: dict) -> dict:
    report = verified.get("report") or {}
    checks = report.get("checks", [])
    if (verified.get("status") != "verified" or verified.get("passed") is not False
            or report.get("passed") is not False
            or [c.get("name") for c in checks] != profile["required_checks"]
            or not any(c.get("passed") is False for c in checks)
            or report.get("suite_hash") != profile["suite_hash"]
            or report.get("policy_hash") != profile["policy_hash"]):
        raise ValueError("repair_requires_complete_current_suite_rejection")
    if len(state.get("tasks", [])) != 1:
        raise ValueError("repair_requires_single_task")
    task = state["tasks"][0]
    record = task.get("verification") or {}
    claim = verified.get("claim") or {}
    if (record.get("passed") is not False or record.get("attempt_id") != claim.get("attempt_id")
            or record.get("candidate_hash") != task.get("candidate_hash")
            or record.get("evidence_hash") != task.get("evidence_hash")
            or any(record.get(k) != claim.get(k) for k in
                   ("candidate_hash", "input_hash", "revision", "suite_hash", "policy_hash"))):
        raise ValueError("fresh_rejection_binding_mismatch")
    return {"candidate_hash": record["candidate_hash"], "evidence_hash": record["evidence_hash"],
            "verifier_attempt_id": record["attempt_id"], "input_hash": record["input_hash"],
            "revision": record["revision"], "suite_hash": record["suite_hash"], "policy_hash": record["policy_hash"],
            "failed_checks": sorted(c["name"] for c in checks if c["passed"] is False)}


def guarded_adapter(original, expected: dict, experiment: dict, attempt: dict, persist):
    called = False
    def build(claim, profile, dependencies, repair=None, *, receipt=None):
        nonlocal called
        try:
            if called or source_digest() != experiment["source_digest"]:
                raise ValueError("duplicate_dispatch_or_changed_source")
            if repair is None or not isinstance(claim.get("repair"), dict):
                raise ValueError("missing_repair_context")
            if any(repair.get(k) != expected[k] or claim["repair"].get(k) != expected[k] for k in BINDINGS):
                raise ValueError("stale_repair_context")
            if digest({k: v for k, v in repair.items() if k != "files"}) != digest(claim["repair"]):
                raise ValueError("repair_feedback_differs_from_lease")
            if (bundle_digest(repair["files"]) != expected["candidate_hash"]
                    or sorted(c["name"] for c in repair["checks"] if c.get("passed") is False) != expected["failed_checks"]):
                raise ValueError("repair_bytes_or_failed_checks_mismatch")
            if experiment["live_builds_dispatched"] >= experiment["max_live_repairs"]:
                raise ValueError("repair_dispatch_limit")
        except (ValueError, TypeError, KeyError) as exc:
            raise worker.BuildFailure("repair replay binding rejected before model invocation", actual_cost=0) from exc
        called = True
        experiment["live_builds_dispatched"] += 1
        attempt.update(model_dispatch_started=True, repair_bindings_checked=True,
                       repair_binding={k: expected[k] for k in BINDINGS},
                       repair_feedback_sha256=digest({k: v for k, v in repair.items() if k != "files"}))
        persist()
        return original(claim, profile, dependencies, repair, receipt=receipt)
    return build


def verification_summary(result: dict) -> dict:
    claim = result.get("claim") or {}
    return {"status": result["status"], "passed": result.get("passed"), "report": result.get("report"),
            "identity": {k: claim[k] for k in ("attempt_id", "candidate_hash", "input_hash", "revision", "suite_hash", "policy_hash") if k in claim}}


def import_seed(run_id: str, files: dict, provenance: dict) -> None:
    with client("builder") as http:
        claim = checked(http.post(f"/v1/runs/{run_id}/claim/build", json={
            "worker_id": "immutable-replay-import", "reserve": 1, "lease_seconds": 120}))
        if not claim:
            raise ValueError("seed_import_claim_unavailable")
        payload = {k: claim[k] for k in ("token", "epoch", "revision", "input_hash")}
        payload.update(files=files, actual_cost=0, provenance=provenance)
        checked(http.post(f"/v1/runs/{run_id}/tasks/{claim['task_id']}/submit", json=payload))


def run_repairs(report: dict, env: dict, expected: dict, profile: dict, persist) -> None:
    run_id = report["run_id"]
    for index in range(report["max_live_repairs"]):
        state = read_state(run_id)
        spent, uncertain = accounting_state(state)
        report.update(state=state["state"], spent_microdollars=spent,
                      accounted_spend_microdollars=spent + state["reserved"],
                      accounting_reconciliation_required=uncertain)
        if uncertain or state["state"] != "ACTIVE":
            report.update(status="INCOMPLETE", stop_reason="run_not_settled_and_active")
            return
        if spent + RESERVATION > report["budget_microdollars"] or report["prior_spend_microdollars"] + spent + RESERVATION > SESSION_CAP:
            report.update(status="INCOMPLETE", stop_reason="insufficient_reservation_headroom")
            return
        attempt = {"number": index + 1, "started_at": now(), "stage": "BUILD_DISPATCHED", "model_dispatch_started": False}
        report["attempts"].append(attempt)
        report["accounted_spend_microdollars"] = spent + RESERVATION
        persist()
        original = worker._eve_build
        with patch.object(worker, "_eve_build", side_effect=guarded_adapter(original, expected, report, attempt, persist)):
            built = worker.build_once(env["GRAPHOS_API_URL"], env["GRAPHOS_BUILDER_TOKEN"], run_id,
                                      builder="eve", worker_id="replay-live-repair", reserve=RESERVATION)
        attempt["build"] = summarize_build(built)
        if built.get("reason"):
            attempt["failure_reason"] = built["reason"]
        state = read_state(run_id)
        spent, uncertain = accounting_state(state)
        report.update(state=state["state"], spent_microdollars=spent,
                      accounted_spend_microdollars=spent + state["reserved"],
                      accounting_reconciliation_required=uncertain)
        if (uncertain or state["state"] == "BUDGET_EXCEEDED" or spent > report["budget_microdollars"]
                or report["prior_spend_microdollars"] + spent > SESSION_CAP):
            report.update(status="INCOMPLETE", stop_reason="accounting_requires_reconciliation")
            attempt.update(stage="STOPPED_AFTER_BUILD", finished_at=now())
            persist()
            return
        if built["status"] != "submitted":
            report.update(status="FAIL", stop_reason="build_failed_no_automatic_retry")
            attempt.update(stage="STOPPED_AFTER_BUILD", finished_at=now())
            persist()
            return
        attempt["stage"] = "VERIFY_DISPATCHED"
        persist()
        verified = worker.verify_once(env["GRAPHOS_API_URL"], env["GRAPHOS_VERIFIER_TOKEN"], run_id,
                                     worker_id="replay-independent-verifier")
        attempt.update(stage="VERIFIED", verification=verification_summary(verified), finished_at=now())
        state = read_state(run_id)
        spent, uncertain = accounting_state(state)
        report.update(state=state["state"], spent_microdollars=spent,
                      accounted_spend_microdollars=spent + state["reserved"],
                      accounting_reconciliation_required=uncertain)
        persist()
        if uncertain:
            report.update(status="INCOMPLETE", stop_reason="accounting_requires_reconciliation")
            return
        candidate = (verified.get("claim") or {}).get("candidate_hash")
        if verified.get("status") == "verified" and verified.get("passed") is True and state["state"] == "READY_FOR_RELEASE":
            if (not attempt["model_dispatch_started"] or candidate == report["seed"]["source_candidate_hash"]
                    or source_digest() != report["source_digest"]):
                report.update(status="INCOMPLETE", stop_reason="distinct_current_source_repair_required")
                return
            report["export"] = export_release(run_id, ROOT / ".state/live-deliveries" / ("replay-" + report["experiment_id"]))
            report["status"] = "PASS"
            return
        if state["state"] != "ACTIVE" or index + 1 == report["max_live_repairs"]:
            report["status"] = "FAIL"
            return
        expected = rejected_binding(verified, state, profile)
    report["status"] = "FAIL"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_report", type=Path)
    parser.add_argument("--candidate-hash", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--prior-spend-microdollars", required=True, type=int)
    parser.add_argument("--max-repairs", type=int, choices=(1, 2), default=2)
    parser.add_argument("--budget", type=int, default=2_000_000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if not args.execute:
        parser.error("--execute is required for bounded paid repairs")
    if not 0 <= args.prior_spend_microdollars < SESSION_CAP or not RESERVATION <= args.budget <= SESSION_CAP - args.prior_spend_microdollars:
        parser.error("budget must fund one reservation and fit the remaining $5 session authorization")
    validate_digest(args.candidate_hash)
    source_bytes = args.source_report.read_bytes()
    source = json.loads(source_bytes)
    stamp = uuid4().hex
    output = args.output or ROOT / "evals/results" / f"repair-replay-{stamp}.json"
    if output.exists():
        parser.error("output already exists; preserve previous evidence")
    report = {"schema_version": 1, "experiment_id": stamp, "mode": "immutable-ai-candidate-replay-and-live-repair",
              "status": "RUNNING", "started_at": now(), "source_digest": source_digest(),
              "source_report": str(args.source_report), "source_report_sha256": hashlib.sha256(source_bytes).hexdigest(),
              "seed_candidate_hash": args.candidate_hash, "seed_import_is_model_generation": False,
              "seed_import_cost_microdollars": 0, "max_live_repairs": args.max_repairs,
              "prior_spend_microdollars": args.prior_spend_microdollars, "budget_microdollars": args.budget,
              "live_builds_dispatched": 0, "accounted_spend_microdollars": 0, "attempts": [],
              "production_certification": False, "counts_toward_first_attempt_pilot": False,
              "gateway_budget_is_soft": True}
    def persist():
        save(output, report)
    persist()
    previous = os.environ.copy()
    api = eve = None
    try:
        env = local_environment()
        controller = {**control_environment(env), "GRAPHOS_ALLOW_FIXTURE": "0"}
        api = ManagedAPI(controller)
        api.start()
        execution_env = {**controller, "GRAPHOS_API_URL": api.url}
        os.environ.clear()
        os.environ.update(execution_env)
        original_state = read_state(source["run_id"])
        with client() as http:
            artifact = checked(http.get(f"/v1/artifacts/{args.candidate_hash}"))
        binding, files, provenance = validate_seed(source, original_state, artifact, args.candidate_hash)
        report["seed"] = binding
        profile = get_profile(binding["source_profile"])
        spec = default_spec(binding["source_profile"])
        spec.update(name=f"Exact rejected-candidate replay: {binding['source_profile']}", max_attempts=args.max_repairs + 1)
        with client() as http:
            run = checked(http.post("/v1/runs", json={"spec": spec, "budget": args.budget, "idempotency_key": "replay-" + stamp}))
        report.update(run_id=str(run["id"]), profile=binding["source_profile"], suite_hash=spec["suite_hash"], policy_hash=spec["policy_hash"])
        persist()
        import_seed(report["run_id"], files, replay_provenance(binding, provenance))
        verified = worker.verify_once(api.url, controller["GRAPHOS_VERIFIER_TOKEN"], report["run_id"], worker_id="replay-seed-verifier")
        report["seed_verification"] = verification_summary(verified)
        persist()
        if verified.get("passed") is True:
            report.update(status="SEED_ALREADY_PASSES", stop_reason="no_repair_needed_no_model_dispatch_or_export")
        else:
            state = read_state(report["run_id"])
            spent, uncertain = accounting_state(state)
            if spent != 0 or uncertain or state["state"] != "ACTIVE":
                raise ValueError("seed_import_not_zero_cost_and_repairable")
            expected = rejected_binding(verified, state, profile)
            if expected["candidate_hash"] != args.candidate_hash:
                raise ValueError("seed_reverification_changed_candidate")
            report["initial_repair_binding"] = expected
            eve = LiveEve({**env, "GRAPHOS_RECEIPT_API_URL": api.url})
            eve.build()
            if source_digest() != report["source_digest"]:
                raise ValueError("source_changed_during_build")
            report["compiled_from_current_source"] = True
            persist()
            eve.start()
            execution_env["EVE_SERVER_URL"] = eve.url
            os.environ.update(execution_env)
            run_repairs(report, execution_env, expected, profile, persist)
    except Exception as exc:
        report.update(status="ERROR", error_type=type(exc).__name__,
                      next_action="Retain evidence and reconcile ledger/provider costs before any new explicit run")
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
                report.update(finished_at=now(), source_unchanged=source_digest() == report["source_digest"],
                              session_accounted_microdollars=args.prior_spend_microdollars + report["accounted_spend_microdollars"])
                if report["status"] == "RUNNING":
                    report["status"] = "INTERRUPTED"
                if not report["source_unchanged"]:
                    report["status"] = "INCOMPLETE"
                persist()
    print(json.dumps({"status": report["status"], "run_id": report.get("run_id"), "result": str(output),
                      "live_builds_dispatched": report["live_builds_dispatched"],
                      "accounted_spend_microdollars": report["accounted_spend_microdollars"]}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
