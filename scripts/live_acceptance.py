"""Explicit bounded live-model acceptance. Never a fixture fallback or production certification.

The caller must verify remaining session authorization and Gateway budget first.
Gateway budgets are soft: this harness controls dispatch, not the provider invoice.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.acceptance import ManagedAPI, local_environment  # noqa: E402
from scripts.check import source_digest  # noqa: E402
from graphos.__main__ import client, checked, export_release  # noqa: E402
from graphos.profiles import default_spec  # noqa: E402
from graphos.worker import build_once, verify_once  # noqa: E402


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def eve_environment(env: dict[str, str]) -> dict[str, str]:
    if not env.get("AI_GATEWAY_API_KEY") or len(env.get("GRAPHOS_EVE_TOKEN", "")) < 32:
        raise ValueError("Gateway and distinct eve broker credentials are required")
    allowed = {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "NODE_EXTRA_CA_CERTS",
               "SSL_CERT_FILE", "SSL_CERT_DIR", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY",
               "https_proxy", "http_proxy", "no_proxy", "AI_GATEWAY_API_KEY", "GRAPHOS_EVE_TOKEN"}
    return {**{k: v for k, v in env.items() if k in allowed}, "GRAPHOS_LIVE_ENABLED": "1",
            "GRAPHOS_GATEWAY_BUDGET_USD": "1", "NODE_USE_ENV_PROXY": "1", "EVE_SCHEDULES_DISABLED": "1"}


def control_environment(env: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in env.items() if not k.startswith(("AI_GATEWAY_", "VERCEL_"))}


def save(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, default=str) + "\n")
    temporary.replace(path)


class LiveEve:
    """One compiled server lifetime. Never restart an uncertain durable request."""
    def __init__(self, env: dict[str, str]):
        self.env = eve_environment(env)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.process: subprocess.Popen | None = None
        log_path = ROOT / ".state" / f"live-eve-{uuid4()}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log = log_path.open("xb")
        os.chmod(log_path, 0o600)

    def build(self) -> None:
        # Never attribute precompiled output to current source. Build without
        # model or role credentials before starting either live service.
        environment = {k: v for k, v in self.env.items()
                       if not k.startswith(("AI_GATEWAY_", "GRAPHOS_", "VERCEL_"))}
        environment["npm_config_cache"] = str(ROOT.parent / ".cache/npm")
        result = subprocess.run(["npm", "run", "build"], cwd=ROOT / "agents/eve",
                                env=environment, stdin=subprocess.DEVNULL,
                                stdout=self.log, stderr=subprocess.STDOUT, timeout=180)
        if result.returncode:
            raise RuntimeError("eve_build_failed")

    def start(self) -> None:
        self.process = subprocess.Popen(
            ["node", "node_modules/eve/bin/eve.js", "start", "--host", "127.0.0.1",
             "--port", str(self.port), "--no-schedules"], cwd=ROOT / "agents/eve",
            env=self.env, stdin=subprocess.DEVNULL, stdout=self.log,
            stderr=subprocess.STDOUT, start_new_session=True)
        deadline = time.monotonic() + 35
        with httpx.Client(timeout=1, trust_env=False) as http:
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError("eve_startup_failed")
                try:
                    if http.get(self.url + "/eve/v1/health").is_success:
                        return
                except httpx.TransportError:
                    pass
                time.sleep(0.1)
        raise RuntimeError("eve_startup_deadline")

    def close(self) -> None:
        if self.process:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            # A child may outlive its launcher; kill the entire owned group.
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.process.wait(timeout=5)
        self.log.close()


def run_attempts(run_id: str, env: dict[str, str], maximum: int, report: dict, persist) -> bool:
    """Only verifier rejection with settled accounting permits the next attempt."""
    for index in range(maximum):
        attempt = {"number": index + 1, "started_at": now(), "stage": "BUILD_DISPATCHED"}
        report["attempts"].append(attempt)
        persist()
        built = build_once(env["GRAPHOS_API_URL"], env["GRAPHOS_BUILDER_TOKEN"], run_id,
                           builder="eve", worker_id="live-acceptance-builder", reserve=1_000_000)
        attempt["build_status"] = built["status"]
        claim = built.get("claim") or {}
        attempt["build_identity"] = {k: claim[k] for k in
            ("attempt_id", "task_id", "epoch", "revision", "input_hash") if k in claim}
        usage = built.get("usage", {})
        attempt["usage"] = {k: usage[k] for k in
            ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
             "actual_cost_microdollars", "model_runs", "cost_source", "generations") if k in usage}
        # Preserve useful identities, never a bearer lease or raw transport error.
        provenance = built.get("provenance", {})
        attempt["provenance"] = {k: provenance[k] for k in
            ("mode", "model", "session_id", "delivery_id", "request_sha256", "catalog_sha256",
             "input_hash", "suite_hash", "policy_hash", "generated_at") if k in provenance}
        with client() as api:
            state = checked(api.get(f"/v1/runs/{run_id}"))
        report.update(state=state["state"], spent_microdollars=state["spent"])
        report["accounting_reconciliation_required"] = state["state"] == "RECONCILIATION_REQUIRED"
        if built["status"] != "submitted" or state["state"] in {
                "RECONCILIATION_REQUIRED", "BUDGET_EXCEEDED", "EXHAUSTED", "CANCELLED"}:
            attempt.update(stage="STOPPED_AFTER_BUILD", finished_at=now())
            persist()
            return False
        attempt["stage"] = "VERIFY_DISPATCHED"
        persist()
        verified = verify_once(env["GRAPHOS_API_URL"], env["GRAPHOS_VERIFIER_TOKEN"], run_id,
                               worker_id="live-acceptance-verifier")
        verification_claim = verified.get("claim") or {}
        attempt["verification_identity"] = {k: verification_claim[k] for k in
            ("attempt_id", "candidate_hash", "input_hash", "suite_hash", "policy_hash")
            if k in verification_claim}
        attempt.update(stage="VERIFIED", verification_status=verified["status"],
                       passed=verified.get("passed", False), report=verified.get("report"), finished_at=now())
        with client() as api:
            state = checked(api.get(f"/v1/runs/{run_id}"))
        report.update(state=state["state"], spent_microdollars=state["spent"])
        persist()
        if state["state"] in {"READY_FOR_RELEASE", "RELEASED"} and verified.get("passed") is True:
            return True
        if (verified["status"] != "verified" or verified.get("passed") is not False
                or state["state"] != "ACTIVE"):
            return False
    return False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Explicitly authorize real model requests")
    parser.add_argument("--max-attempts", type=int, choices=(1, 2), default=1)
    parser.add_argument("--budget", type=int, default=1_000_000, help="Run microdollars, at most 5,000,000")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    if not args.execute:
        parser.error("--execute is required; this command makes real paid model requests")
    if not 1_000_000 <= args.budget <= 5_000_000:
        parser.error("budget must be between 1,000,000 and 5,000,000 microdollars")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]
    output = args.output or ROOT / "evals/results" / f"live-{stamp}.json"
    if output.exists():
        parser.error("output already exists; retain every prior live attempt")
    env = local_environment()
    eve = LiveEve(env)
    controller_env = control_environment(env)
    controller_env["GRAPHOS_ALLOW_FIXTURE"] = "0"
    api = ManagedAPI(controller_env)
    report = {"schema_version": 1, "mode": "live-model", "status": "RUNNING", "started_at": now(),
              "source_digest": source_digest(), "max_attempts": args.max_attempts,
              "budget_microdollars": args.budget, "attempt_reservation_microdollars": 1_000_000,
              "gateway_budget_is_soft": True, "attempts": [], "production_certification": False,
              "limits": ["One fixed static-web task-list contract", "No statistical reliability estimate",
                         "Operator must reconcile remaining session spend before dispatch",
                         "Process termination does not guarantee provider cancellation"]}
    def persist():
        save(output, report)
    persist()
    previous = os.environ.copy()
    try:
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
        spec = default_spec()
        spec.update(name="GraphOS live task-list acceptance", max_attempts=args.max_attempts)
        with client() as http:
            run = checked(http.post("/v1/runs", json={"spec": spec, "budget": args.budget,
                                                     "idempotency_key": f"live-{stamp}"}))
        report["run_id"] = str(run["id"])
        persist()
        accepted = run_attempts(report["run_id"], execution_env, args.max_attempts, report, persist)
        if accepted:
            report["export"] = export_release(report["run_id"], ROOT / ".state/live-deliveries" / stamp)
        report["status"] = "PASS" if accepted else "FAIL"
    except Exception as exc:
        report.update(status="ERROR", error_type=type(exc).__name__,
                      next_action="Inspect private logs and ledger; reconcile uncertain cost before retry")
    finally:
        try:
            eve.close()
        finally:
            api.close()
            os.environ.clear()
            os.environ.update(previous)
            report.update(finished_at=now(), source_unchanged=source_digest() == report["source_digest"])
            if report["status"] == "RUNNING":
                report["status"] = "INTERRUPTED"
            if report["status"] == "PASS" and not report["source_unchanged"]:
                report["status"] = "INCOMPLETE"
            persist()
    print(json.dumps({"status": report["status"], "run_id": report.get("run_id"), "result": str(output),
                      "spent_microdollars": report.get("spent_microdollars"), "production_certification": False}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
