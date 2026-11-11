"""One explicit controlled persistence fault followed by at most one live repair.

This is a hybrid fault-injection experiment, not a natural model failure rate.
The operator must review remaining session spend before --execute.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.live_acceptance import (  # noqa: E402
    LiveEve, ManagedAPI, local_environment, control_environment, now, save,
)
from scripts.check import source_digest  # noqa: E402
from scripts.acceptance import AcceptanceHarness  # noqa: E402
from graphos import worker  # noqa: E402
from graphos.__main__ import export_release  # noqa: E402
from graphos.artifacts import bundle_digest, validate_digest, validate_files  # noqa: E402
from graphos.profiles import default_spec  # noqa: E402

MUTATION = "// GraphOS controlled persistence fault; remove to restore storage.\nStorage.prototype.setItem = function () {};\n"


def load_seed(path: Path) -> tuple[dict, dict[str, str]]:
    """Validate a single-task exported release and its full candidate bytes."""
    path = path.resolve(strict=True)
    manifest = json.loads((path / "release.json").read_text())
    fields = ("run_id", "revision", "spec_hash", "profile", "tasks")
    encoded = json.dumps({k: manifest[k] for k in fields}, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode()
    if hashlib.sha256(encoded).hexdigest() != validate_digest(manifest["manifest_hash"]):
        raise ValueError("seed_release_manifest_mismatch")
    if manifest["profile"] != "static-web" or len(manifest["tasks"]) != 1:
        raise ValueError("seed_must_be_single_static_web_release")
    task = manifest["tasks"][0]
    if task.get("provenance", {}).get("mode") != "eve":
        raise ValueError("seed_must_be_genuine_live_model_release")
    key = task["task_key"]
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", key):
        raise ValueError("unsafe_seed_task_key")
    root = path / key
    if root.is_symlink() or any((root / name).is_symlink() for name in ("index.html", "app.js", "styles.css")):
        raise ValueError("seed_symlinks_forbidden")
    files = {name: (root / name).read_text(encoding="utf-8")
             for name in ("index.html", "app.js", "styles.css")}
    validate_files(files)
    if bundle_digest(files) != validate_digest(task["candidate_hash"]):
        raise ValueError("seed_candidate_hash_mismatch")
    return manifest, files


def repair_guard(claim: dict, repair: dict | None, rejected: dict) -> None:
    if repair is None or claim.get("repair") is None:
        raise ValueError("repair_context_missing")
    for key in ("candidate_hash", "evidence_hash", "verifier_attempt_id", "input_hash", "revision", "suite_hash", "policy_hash"):
        if repair.get(key) != rejected[key] or claim["repair"].get(key) != rejected[key]:
            raise ValueError("repair_binding_mismatch")
    if bundle_digest(repair["files"]) != rejected["candidate_hash"]:
        raise ValueError("repair_files_mismatch")
    if not any(c["name"] == "local_storage_reload" and c["passed"] is False for c in repair["checks"]):
        raise ValueError("repair_persistence_failure_missing")


def summarize_build(result: dict) -> dict:
    claim, provenance, usage = result.get("claim") or {}, result.get("provenance", {}), result.get("usage", {})
    return {"status": result["status"],
            "identity": {k: claim[k] for k in ("attempt_id", "task_id", "epoch", "revision", "input_hash") if k in claim},
            "provenance": {k: provenance[k] for k in ("mode", "model", "session_id", "delivery_id", "request_sha256",
                "catalog_sha256", "input_hash", "suite_hash", "policy_hash", "generated_at") if k in provenance},
            "usage": {k: usage[k] for k in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
                "actual_cost_microdollars", "model_runs", "cost_source", "generations") if k in usage}}


def guarded_adapter(original_build, rejected_binding: dict, report: dict, persist):
    def build(build_claim, profile, dependencies, repair=None, *, receipt=None):
        try:
            repair_guard(build_claim, repair, rejected_binding)
        except (ValueError, KeyError, TypeError) as exc:
            raise worker.BuildFailure("controlled repair binding rejected before model invocation", actual_cost=0) from exc
        if report["live_builds_dispatched"] != 0:
            raise worker.BuildFailure("extra live build rejected before model invocation", actual_cost=0)
        report.update(live_builds_dispatched=1, repair_bindings_checked_before_dispatch=True)
        persist()
        return original_build(build_claim, profile, dependencies, repair, receipt=receipt)
    return build


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("seed_export", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if not args.execute:
        parser.error("--execute is required for the single paid repair request")
    seed, files = load_seed(args.seed_export)
    mutated = {**files, "app.js": MUTATION + files["app.js"]}
    validate_files(mutated)
    seed_task = seed["tasks"][0]
    stamp = uuid4().hex
    output = args.output or ROOT / "evals/results" / f"controlled-repair-{stamp}.json"
    if output.exists():
        parser.error("output exists; retain earlier results")
    env = local_environment()
    base_env = control_environment(env)
    # Only this short-lived private injection controller admits fixtures.
    injection = ManagedAPI({**base_env, "GRAPHOS_ALLOW_FIXTURE": "1"})
    live = ManagedAPI({**base_env, "GRAPHOS_ALLOW_FIXTURE": "0"})
    eve = LiveEve(env)
    injection_http = live_http = None
    previous = os.environ.copy()
    report = {"schema_version": 1, "mode": "controlled-fault-live-repair", "status": "RUNNING",
              "started_at": now(), "source_digest": source_digest(), "production_certification": False,
              "max_live_builds": 1, "max_run_attempts": 2, "run_budget_microdollars": 1_000_000,
              "seed_run_id": seed["run_id"], "seed_release_manifest_hash": seed["manifest_hash"],
              "seed_candidate_hash": seed_task["candidate_hash"], "mutation": "disable Storage.prototype.setItem",
              "mutated_candidate_hash": bundle_digest(mutated), "live_builds_dispatched": 0,
              "limits": ["Controlled seeded defect, not natural failure rate", "One disclosed task-list profile",
                         "Gateway soft budget is not a hard invoice cap", "No production certification"]}
    def persist():
        save(output, report)
    persist()
    try:
        eve.build()
        if source_digest() != report["source_digest"]:
            raise RuntimeError("source_changed_during_build")
        report["compiled_from_current_source"] = True
        injection.start()
        injection_env = {**base_env, "GRAPHOS_API_URL": injection.url}
        os.environ.clear()
        os.environ.update(injection_env)
        injection_http = AcceptanceHarness(injection.url, injection_env)
        authoritative = injection_http.request("GET", f"/v1/runs/{seed['run_id']}/release").json()
        if authoritative["manifest_hash"] != seed["manifest_hash"]:
            raise ValueError("seed_export_does_not_match_authoritative_release")
        spec = default_spec()
        spec.update(name="GraphOS controlled persistence repair", max_attempts=2)
        run_id, _ = injection_http.create(spec=spec, key="controlled-repair-" + stamp)
        report["run_id"] = run_id
        persist()
        claim = injection_http.claim_build(run_id, reserve=1)
        payload = {key: claim[key] for key in ("token", "epoch", "revision", "input_hash")}
        payload.update(files=mutated, actual_cost=0, provenance={"mode": "fixture",
            "fixture": "controlled-persistence-mutation", "ai_generated": False,
            "source_candidate_hash": seed_task["candidate_hash"], "source_release_hash": seed["manifest_hash"]})
        injection_http.request("POST", f"/v1/runs/{run_id}/tasks/{claim['task_id']}/submit", role="builder", body=payload)
        rejected = worker.verify_once(injection.url, base_env["GRAPHOS_VERIFIER_TOKEN"], run_id,
                                      worker_id="controlled-fault-verifier")
        report["injected_verification"] = {"passed": rejected.get("passed"), "report": rejected.get("report")}
        persist()
        if rejected.get("passed") is not False or not any(
                check["name"] == "local_storage_reload" and check["passed"] is False
                for check in rejected.get("report", {}).get("checks", [])):
            raise RuntimeError("controlled_persistence_fault_not_rejected")
        injection_http.request("GET", f"/v1/runs/{run_id}/release", expected=(409,))
        state = injection_http.state(run_id)
        if state["state"] != "ACTIVE" or state["spent"] != 0:
            raise RuntimeError("injected_run_not_eligible_for_bounded_repair")
        task = next(t for t in state["tasks"] if t["id"] == claim["task_id"])
        rejected_binding = {key: rejected["claim"][key] for key in
                            ("candidate_hash", "input_hash", "revision", "suite_hash", "policy_hash")}
        rejected_binding["evidence_hash"] = task["evidence_hash"]
        rejected_binding["verifier_attempt_id"] = rejected["claim"]["attempt_id"]
        if rejected_binding["candidate_hash"] != report["mutated_candidate_hash"]:
            raise RuntimeError("rejected_candidate_mismatch")
        report.update(rejected_bindings=rejected_binding, release_blocked_before_repair=True)
        persist()
        injection_http.close()
        injection_http = None
        injection.close()
        live.start()
        eve.env["GRAPHOS_RECEIPT_API_URL"] = live.url
        eve.start()
        execution_env = {**base_env, "GRAPHOS_API_URL": live.url, "EVE_SERVER_URL": eve.url,
                         "GRAPHOS_ALLOW_FIXTURE": "0"}
        os.environ.clear()
        os.environ.update(execution_env)
        live_http = AcceptanceHarness(live.url, execution_env)
        original_build = worker._eve_build
        # This guard delegates the unchanged real adapter; it supplies no model output.
        with patch.object(worker, "_eve_build", side_effect=guarded_adapter(original_build, rejected_binding, report, persist)):
            built = worker.build_once(live.url, base_env["GRAPHOS_BUILDER_TOKEN"], run_id,
                                      builder="eve", worker_id="controlled-live-repair", reserve=1_000_000)
        report["live_build"] = summarize_build(built)
        state = live_http.state(run_id)
        report.update(state=state["state"], spent_microdollars=state["spent"],
                      accounting_reconciliation_required=state["state"] == "RECONCILIATION_REQUIRED")
        persist()
        if built["status"] != "submitted":
            report["status"] = "FAIL"
        else:
            verified = worker.verify_once(live.url, base_env["GRAPHOS_VERIFIER_TOKEN"], run_id,
                                          worker_id="controlled-repair-independent-verifier")
            report["repaired_verification"] = {"passed": verified.get("passed"), "report": verified.get("report"),
                "identity": {key: verified["claim"][key] for key in
                    ("attempt_id", "candidate_hash", "revision", "input_hash", "suite_hash", "policy_hash")}}
            if verified["claim"]["attempt_id"] == rejected["claim"]["attempt_id"]:
                raise RuntimeError("old_verification_reused")
            state = live_http.state(run_id)
            report.update(state=state["state"], spent_microdollars=state["spent"])
            if verified.get("passed") is True and state["state"] == "READY_FOR_RELEASE":
                report["export"] = export_release(run_id, ROOT / ".state/live-deliveries" / ("repair-" + stamp))
                report["status"] = "PASS"
            else:
                report["status"] = "FAIL"
    except Exception as exc:
        report.update(status="ERROR", error_type=type(exc).__name__,
                      next_action="Inspect private ledger/logs and reconcile uncertain cost before retry")
    finally:
        if injection_http is not None:
            injection_http.close()
        if live_http is not None:
            live_http.close()
        try:
            eve.close()
        finally:
            injection.close()
            live.close()
            os.environ.clear()
            os.environ.update(previous)
            report.update(finished_at=now(), source_unchanged=source_digest() == report["source_digest"])
            if report["status"] == "RUNNING":
                report["status"] = "INTERRUPTED"
            if report["status"] == "PASS" and not report["source_unchanged"]:
                report["status"] = "INCOMPLETE"
            persist()
    print(json.dumps({"status": report["status"], "run_id": report.get("run_id"), "result": str(output),
                      "live_builds_dispatched": report["live_builds_dispatched"],
                      "spent_microdollars": report.get("spent_microdollars"), "production_certification": False}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
