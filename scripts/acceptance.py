"""HTTP/product acceptance checks; fixture success is never model quality evidence.

Run with --managed to start and restart a real API process using the configured
PostgreSQL database. No candidate code is executed by this harness on the host.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Any, Callable
from unittest.mock import patch
from uuid import uuid4

import httpx


ROOT = Path(__file__).resolve().parents[1]
def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def local_environment() -> dict[str, str]:
    """Read the documented private local config without printing secret values."""
    env = os.environ.copy()
    path = ROOT / ".state" / "local.env"
    if path.exists():
        for line in path.read_text().splitlines():
            if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            name = name.strip().removeprefix("export ")
            if name.startswith(("GRAPHOS_", "AI_GATEWAY_", "VERCEL_")):
                env.setdefault(name, value.strip().strip("\"'"))
    return env


class ManagedAPI:
    """A genuine controller process; stop/start retains its database and artifacts."""

    def __init__(self, env: dict[str, str], port: int | None = None):
        self.env = env.copy()
        if port is None:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
        self.url = f"http://127.0.0.1:{port}"
        self.port = port
        self.process: subprocess.Popen | None = None
        # No controller logs are copied into public acceptance results.
        self.log_path = ROOT / ".state" / f"acceptance-api-{port}.log"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log = self.log_path.open("ab")

    def start(self) -> None:
        self.process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "graphos.api:create_app", "--factory",
             "--host", "127.0.0.1", "--port", str(self.port)],
            cwd=ROOT, env=self.env, stdout=self.log, stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + 30
        with httpx.Client(timeout=1, trust_env=False) as client:
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError("API process exited before readiness; inspect private controller log")
                try:
                    result = client.get(f"{self.url}/v1/profiles", headers={
                        "Authorization": f"Bearer {self.env['GRAPHOS_OPERATOR_TOKEN']}"})
                    if result.status_code == 200:
                        return
                except httpx.TransportError:
                    pass
                time.sleep(0.1)
        raise RuntimeError("API readiness deadline exceeded")

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)

    def restart(self) -> None:
        self.stop()
        self.start()

    def close(self) -> None:
        self.stop()
        self.log.close()


class AcceptanceHarness:
    def __init__(self, api_url: str, env: dict[str, str],
                 restart_controller: Callable[[], None] | None = None):
        self.api_url = api_url.rstrip("/")
        self.env = env
        self.tokens = {role: env[f"GRAPHOS_{role.upper()}_TOKEN"]
                       for role in ("operator", "builder", "verifier")}
        self.restart_controller = restart_controller
        self.client = httpx.Client(base_url=self.api_url, timeout=240, trust_env=False)
        self.profile: dict[str, Any] | None = None
        self.completed_fixture_run: str | None = None
        self.results: dict[str, Any] = {
            "schema_version": 1, "started_at": utcnow(), "mode": "integration-fixture",
            "cases": [], "claims": {
                "model_quality_measured": False, "production_readiness_established": False,
                "scope": "PostgreSQL HTTP control plane and Docker static-web verification",
            },
            "limits": ["One supported static-web profile", "Deterministic fixtures are not AI generation",
                       "No live deployment or financial execution", "No statistical accuracy estimate",
                       "Controller restart is not a database disaster-recovery test"],
        }

    def close(self) -> None:
        self.client.close()

    def request(self, method: str, path: str, *, role: str | None = "operator",
                body: dict | None = None, expected: tuple[int, ...] = (200, 201),
                lease: dict | None = None) -> httpx.Response:
        headers = {} if role is None else {"Authorization": f"Bearer {self.tokens[role]}"}
        if lease:
            headers.update({"X-GraphOS-Run-Id": str(lease["run_id"]),
                            "X-GraphOS-Task-Id": str(lease["task_id"]),
                            "X-GraphOS-Lease-Token": lease["token"],
                            "X-GraphOS-Lease-Epoch": str(lease["epoch"])})
        response = self.client.request(method, path, headers=headers, json=body)
        if response.status_code not in expected:
            # Deliberately omit response/request bodies: these can contain lease tokens.
            raise AssertionError(f"{method} {path} returned HTTP {response.status_code}; expected {expected}")
        return response

    @staticmethod
    def claim_value(value: Any) -> dict | None:
        return value.get("claim", value) if isinstance(value, dict) else value

    @staticmethod
    def run_id(value: dict) -> str:
        return str(value.get("run_id") or value["id"])

    def spec(self) -> dict:
        if self.profile is None:
            data = self.request("GET", "/v1/profiles").json()
            profiles = data.get("profiles", data) if isinstance(data, dict) else data
            self.profile = next(p for p in profiles if p["id"] == "static-web")
        return {"name": "GraphOS HTTP acceptance fixture", "profile": "static-web",
                "requirements": list(self.profile["acceptance_criteria"]),
                "tasks": [dict(task) for task in self.profile["task_template"]],
                "suite_hash": self.profile["suite_hash"], "policy_hash": self.profile["policy_hash"],
                "max_attempts": 2}

    def create(self, *, spec: dict | None = None, key: str | None = None) -> tuple[str, dict]:
        payload = {"spec": spec or self.spec(), "budget": 1000000,
                   "idempotency_key": key or f"acceptance-{uuid4()}"}
        data = self.request("POST", "/v1/runs", body=payload).json()
        return self.run_id(data), payload

    def state(self, run_id: str) -> dict:
        return self.request("GET", f"/v1/runs/{run_id}").json()

    def claim_build(self, run_id: str, *, lease_seconds: int = 120, reserve: int = 10) -> dict:
        claim = self.claim_value(self.request("POST", f"/v1/runs/{run_id}/claim/build", role="builder", body={
            "worker_id": "acceptance-builder", "reserve": reserve, "lease_seconds": lease_seconds}).json())
        assert claim, "Expected an eligible build claim"
        return claim

    def submit_fixture(self, run_id: str, *, files: dict | None = None) -> tuple[dict, dict]:
        from graphos.profiles import fixture_files
        claim = self.claim_build(run_id)
        payload = {name: claim[name] for name in ("token", "epoch", "revision", "input_hash")}
        payload.update(files=files if files is not None else fixture_files(), actual_cost=0,
                       provenance={"mode": "fixture", "fixture": "static-web/task-list",
                                   "purpose": "HTTP acceptance; not model generation"})
        self.request("POST", f"/v1/runs/{run_id}/tasks/{claim['task_id']}/submit",
                     role="builder", body=payload)
        return claim, payload

    def verify_direct(self, run_id: str, *, altered_hash_first: bool = False) -> tuple[dict, dict, dict]:
        from graphos.sandbox import verify_bundle
        claim = self.claim_value(self.request("POST", f"/v1/runs/{run_id}/claim/verify", role="verifier", body={
            "worker_id": "acceptance-verifier", "lease_seconds": 240}).json())
        assert claim, "Expected an eligible verification claim"
        bundle = self.request("GET", f"/v1/artifacts/{claim['candidate_hash']}", role="verifier", lease=claim).json()
        files = bundle.get("files", bundle)
        report = verify_bundle(files, claim["requirements"])
        assert report["passed"] is True, "Trusted Docker/browser suite rejected the valid fixture"
        payload = {name: claim[name] for name in ("token", "epoch", "revision", "input_hash",
                                                     "candidate_hash", "suite_hash", "policy_hash")}
        payload.update(passed=True, report=report)
        path = f"/v1/runs/{run_id}/tasks/{claim['task_id']}/verify"
        if altered_hash_first:
            bad = dict(payload, candidate_hash="0" * 64)
            self.request("POST", path, role="verifier", body=bad, expected=(409, 422))
            incomplete = dict(payload, report=dict(report, checks=report["checks"][:1]))
            self.request("POST", path, role="verifier", body=incomplete, expected=(422,))
            self.request("GET", f"/v1/runs/{run_id}/release", expected=(409,))
        self.request("POST", path, role="verifier", body=payload)
        return claim, payload, report

    def happy_fixture_release(self) -> dict:
        from graphos.worker import build_once, verify_once
        run_id, _ = self.create()
        self.request("GET", f"/v1/runs/{run_id}/release", expected=(409,))
        build = build_once(self.api_url, self.tokens["builder"], run_id, builder="fixture",
                           worker_id="acceptance-real-builder-worker")
        assert build["status"] == "submitted"
        verify = verify_once(self.api_url, self.tokens["verifier"], run_id,
                             worker_id="acceptance-real-verifier-worker")
        assert verify["passed"] is True
        release = self.request("GET", f"/v1/runs/{run_id}/release").json()
        state = self.state(run_id)
        assert all(task["state"] == "ACCEPTED" for task in state["tasks"])
        assert state["spent"] + state["reserved"] <= state["budget"]
        assert "fixture" in json.dumps(state).lower(), "Fixture provenance must survive in durable run history"
        self.completed_fixture_run = run_id
        return {"run_id": run_id, "release": release, "verifier_report": verify["report"],
                "provenance": "fixture", "worker_modes": ["fixture-builder", "docker-verifier"]}

    def duplicate_admission_and_submission(self) -> dict:
        run_id, admission = self.create()
        duplicate = self.request("POST", "/v1/runs", body=admission).json()
        assert self.run_id(duplicate) == run_id
        changed = dict(admission, budget=admission["budget"] + 1)
        self.request("POST", "/v1/runs", body=changed, expected=(409,))
        claim, payload = self.submit_fixture(run_id)
        before = self.state(run_id)
        self.request("POST", f"/v1/runs/{run_id}/tasks/{claim['task_id']}/submit", role="builder", body=payload)
        after = self.state(run_id)
        assert (before["spent"], before["reserved"]) == (after["spent"], after["reserved"])
        changed_payload = dict(payload, files=dict(payload["files"], **{"app.js": "// different bytes"}))
        self.request("POST", f"/v1/runs/{run_id}/tasks/{claim['task_id']}/submit", role="builder",
                     body=changed_payload, expected=(409,))
        return {"run_id": run_id, "duplicate_charge": False}

    def registered_profile_boundary(self) -> dict:
        spec = self.spec()
        spec["tasks"][0] = dict(spec["tasks"][0], objective="Build an automated trading strategy and certify profitability")
        self.request("POST", "/v1/runs", body={"spec": spec, "budget": 1000000,
                     "idempotency_key": f"unsupported-objective-{uuid4()}"}, expected=(422,))
        spec = self.spec()
        spec["requirements"].append("Support arbitrary server-side payment processing")
        self.request("POST", "/v1/runs", body={"spec": spec, "budget": 1000000,
                     "idempotency_key": f"unsupported-requirement-{uuid4()}"}, expected=(422,))
        return {"unsupported_objective_rejected": True, "unsupported_requirement_rejected": True,
                "fixed_suite_scope": "registered static-web task-list contract only"}

    def roles_and_cancellation(self) -> dict:
        self.request("GET", "/v1/runs", role=None, expected=(401, 403))
        run_id, _ = self.create()
        claim = self.claim_build(run_id)
        self.request("POST", f"/v1/runs/{run_id}/claim/verify", role="builder",
                     body={"worker_id": "builder-pretending-verifier", "lease_seconds": 120}, expected=(403,))
        forbidden_receipt = {name: claim[name] for name in ("token", "epoch", "revision", "input_hash",
                                                               "suite_hash", "policy_hash")}
        forbidden_receipt.update(candidate_hash="0" * 64, passed=False,
                                 report={"passed": False, "checks": [{"name": "role_boundary", "passed": False}]})
        self.request("POST", f"/v1/runs/{run_id}/tasks/{claim['task_id']}/verify", role="builder",
                     body=forbidden_receipt, expected=(403,))
        self.request("POST", f"/v1/runs/{run_id}/effects", body={
            "key": "acceptance-record-only", "payload_hash": "1" * 64, "receiver_deduplicates": False})
        self.request("POST", f"/v1/runs/{run_id}/cancel")
        state = self.state(run_id)
        assert state["state"] == "CANCELLED"
        response = self.request("POST", f"/v1/runs/{run_id}/claim/build", role="builder", body={
            "worker_id": "late-builder", "reserve": 1, "lease_seconds": 120}, expected=(200, 409))
        if response.status_code == 200:
            assert self.claim_value(response.json()) is None
        self.request("POST", f"/v1/runs/{run_id}/effects/begin",
                     body={"key": "acceptance-record-only"}, expected=(409,))
        payload = {name: claim[name] for name in ("token", "epoch", "revision", "input_hash")}
        from graphos.profiles import fixture_files
        payload.update(files=fixture_files(), actual_cost=0, provenance={"mode": "fixture"})
        self.request("POST", f"/v1/runs/{run_id}/tasks/{claim['task_id']}/submit",
                     role="builder", body=payload, expected=(409,))
        self.request("GET", f"/v1/runs/{run_id}/release", expected=(409,))
        return {"run_id": run_id, "state": "CANCELLED", "stale_build_rejected": True,
                "effect_dispatch_blocked": True, "real_external_action_performed": False}

    def evidence_revision_and_artifact_binding(self) -> dict:
        run_id, admission = self.create()
        self.submit_fixture(run_id)
        claim, receipt, report = self.verify_direct(run_id, altered_hash_first=True)
        release = self.request("GET", f"/v1/runs/{run_id}/release").json()
        before = self.state(run_id)
        path = f"/v1/runs/{run_id}/tasks/{claim['task_id']}/verify"
        # A duplicate receipt may be idempotent or rejected, but cannot charge or mutate evidence.
        self.request("POST", path, role="verifier", body=receipt, expected=(200, 409))
        replay = self.state(run_id)
        assert before["spent"] == replay["spent"] and before["reserved"] == replay["reserved"]
        assert release == self.request("GET", f"/v1/runs/{run_id}/release").json()
        new_spec = dict(admission["spec"], name="Revised acceptance fixture requirements")
        self.request("POST", f"/v1/runs/{run_id}/revise", body={
            "spec": new_spec, "expected_revision": before["revision"]})
        after = self.state(run_id)
        assert after["revision"] > before["revision"]
        assert all(task["state"] != "ACCEPTED" for task in after["tasks"])
        self.request("GET", f"/v1/runs/{run_id}/release", expected=(409,))
        self.request("POST", path, role="verifier", body=receipt, expected=(409,))
        return {"run_id": run_id, "previous_release": release, "revision": after["revision"],
                "verifier_report": report, "stale_receipt_rejected": True,
                "incomplete_certificate_rejected": True}

    def bad_candidate_fails_browser(self) -> dict:
        from graphos.profiles import fixture_files
        from graphos.worker import verify_once
        spec = self.spec()
        spec["max_attempts"] = 1
        run_id, _ = self.create(spec=spec)
        files = dict(fixture_files(), **{"app.js": "// Deliberately broken acceptance fixture: no task behaviors."})
        self.submit_fixture(run_id, files=files)
        verification = verify_once(self.api_url, self.tokens["verifier"], run_id,
                                   worker_id="acceptance-negative-verifier")
        assert verification["passed"] is False, "Broken candidate passed the trusted browser suite"
        assert self.profile is not None
        assert [check["name"] for check in verification["report"]["checks"]] == self.profile["required_checks"], \
            "Negative fixture must fail executed browser behavior checks, not unavailable infrastructure"
        assert verification["report"].get("image_id"), "Browser evidence must identify its actual Docker image"
        assert any(check["passed"] is False for check in verification["report"]["checks"])
        self.request("GET", f"/v1/runs/{run_id}/release", expected=(409,))
        assert all(task["state"] != "ACCEPTED" for task in self.state(run_id)["tasks"])
        return {"run_id": run_id, "verifier_report": verification["report"], "provenance": "broken-fixture"}

    def worker_crash_and_lease_recovery(self) -> dict:
        run_id, _ = self.create()
        child_env = self.env.copy()
        child_env.update(ACCEPTANCE_API=self.api_url, ACCEPTANCE_RUN=run_id)
        # This worker exits abruptly immediately after acquiring a real HTTP lease.
        code = """import json, os, httpx
r = httpx.post(os.environ['ACCEPTANCE_API']+'/v1/runs/'+os.environ['ACCEPTANCE_RUN']+'/claim/build',
    headers={'Authorization':'Bearer '+os.environ['GRAPHOS_BUILDER_TOKEN']},
    json={'worker_id':'crash-injected-worker','reserve':13,'lease_seconds':1}, timeout=10, trust_env=False)
r.raise_for_status()
print(json.dumps(r.json()), flush=True)
os._exit(137)
"""
        crashed = subprocess.run([sys.executable, "-c", code], env=child_env, cwd=ROOT,
                                 capture_output=True, timeout=15, text=True)
        assert crashed.returncode == 137, "Injected worker did not reach the intended crash point"
        old = self.claim_value(json.loads(crashed.stdout))
        assert old
        deadline = time.monotonic() + 8
        paused = None
        while time.monotonic() < deadline:
            response = self.request("POST", f"/v1/runs/{run_id}/claim/build", role="builder", body={
                "worker_id": "recovery-worker", "reserve": 7, "lease_seconds": 120}, expected=(200, 409))
            if response.status_code == 200:
                assert self.claim_value(response.json()) is None, \
                    "Uncertain crashed-worker cost must block replacement dispatch"
            state = self.state(run_id)
            if state["state"] == "RECONCILIATION_REQUIRED":
                paused = state
                break
            time.sleep(0.15)
        assert paused, "Expired crashed-worker lease did not enter reconciliation pause"
        assert paused["spent"] >= 13 and paused["reserved"] == 0
        assert any(attempt["attempt_id"] == old["attempt_id"] for attempt in paused["uncertain_cost_attempts"])
        # The injected process exited immediately after claim, before invoking any
        # builder/model/tool. Zero is therefore this fixture's known actual cost.
        receipt = {"attempt_id": old["attempt_id"], "receipt_id": f"acceptance-crash-{uuid4()}", "actual_cost": 0}
        self.request("POST", f"/v1/runs/{run_id}/costs/reconcile", body=receipt)
        reconciled = self.state(run_id)
        assert reconciled["state"] == "ACTIVE" and not reconciled["uncertain_cost_attempts"]
        assert reconciled["spent"] == 0
        self.request("POST", f"/v1/runs/{run_id}/costs/reconcile", body=receipt)
        assert self.state(run_id)["spent"] == 0, "Duplicate cost receipt changed settled spend"
        replacement = self.claim_build(run_id, reserve=7)
        assert replacement["epoch"] > old["epoch"]
        from graphos.profiles import fixture_files
        stale = {name: old[name] for name in ("token", "epoch", "revision", "input_hash")}
        stale.update(files=fixture_files(), actual_cost=0, provenance={"mode": "fixture"})
        self.request("POST", f"/v1/runs/{run_id}/tasks/{old['task_id']}/submit", role="builder",
                     body=stale, expected=(409,))
        state = self.state(run_id)
        assert state["spent"] == 0, "Only authoritative reconciliation may clear conservative spend"
        assert state["reserved"] == 7
        recovered = {name: replacement[name] for name in ("token", "epoch", "revision", "input_hash")}
        recovered.update(files=fixture_files(), actual_cost=0,
                         provenance={"mode": "fixture", "purpose": "recovered crash attempt"})
        self.request("POST", f"/v1/runs/{run_id}/tasks/{replacement['task_id']}/submit", role="builder",
                     body=recovered)
        finished = self.state(run_id)
        assert finished["reserved"] == 0 and finished["spent"] == 0
        assert any(task["state"] == "SUBMITTED" for task in finished["tasks"])
        return {"run_id": run_id, "worker_exit_code": 137, "expired_reservation_conservatively_charged": 13,
                "uncertainty_paused_dispatch": True, "authoritative_fixture_cost_after_reconciliation": 0,
                "new_epoch": replacement["epoch"], "stale_submission_rejected": True,
                "replacement_artifact_submitted": True}

    def controller_restart_preserves_state(self) -> dict:
        if self.restart_controller is None:
            return {"status": "NOT_RUN", "reason": "External API mode cannot restart its controller; use --managed"}
        run_id = self.completed_fixture_run
        assert run_id, "A genuinely browser-verified fixture run is required for the restart check"
        before = self.state(run_id)
        release_before = self.request("GET", f"/v1/runs/{run_id}/release").json()
        old_bundle_hash = next(t["candidate_hash"] for t in before["tasks"] if t.get("candidate_hash"))
        self.restart_controller()
        after = self.state(run_id)
        for field in ("revision", "spec_hash", "state", "spent", "reserved", "budget"):
            assert before[field] == after[field], f"Controller restart changed {field}"
        assert before["tasks"] == after["tasks"]
        assert before["events"] == after["events"]
        self.request("GET", f"/v1/artifacts/{old_bundle_hash}")
        assert release_before == self.request("GET", f"/v1/runs/{run_id}/release").json()
        return {"run_id": run_id, "candidate_hash": old_bundle_hash, "process_restarted": True,
                "preserved": ["accepted task", "events", "budget", "artifact", "evidence", "release bindings"]}

    def run_case(self, name: str, function: Callable[[], dict]) -> dict:
        started = time.monotonic()
        try:
            details = function()
            result = {"id": name, "status": details.pop("status", "PASS"), "details": details}
        except Exception as exc:
            # Errors generated by this harness and WorkerError omit credentials.
            message = str(exc)
            for secret in self.tokens.values():
                message = message.replace(secret, "[REDACTED]")
            result = {"id": name, "status": "FAIL", "error_type": type(exc).__name__, "error": message[:1000]}
        result["duration_ms"] = round((time.monotonic() - started) * 1000)
        self.results["cases"].append(result)
        return result

    def run_all(self, *, include_live: bool = False) -> dict:
        runtime_names = ("GRAPHOS_VERIFIER_IMAGE", "GRAPHOS_VERIFIER_IMAGE_DIGEST")
        with patch.dict(os.environ, {name: self.env[name] for name in runtime_names if name in self.env}):
            return self._run_all(include_live=include_live)

    def _run_all(self, *, include_live: bool = False) -> dict:
        cases = [self.happy_fixture_release, self.duplicate_admission_and_submission,
                 self.registered_profile_boundary,
                 self.roles_and_cancellation, self.evidence_revision_and_artifact_binding,
                 self.bad_candidate_fails_browser, self.worker_crash_and_lease_recovery,
                 self.controller_restart_preserves_state]
        for case in cases:
            self.run_case(case.__name__, case)
        has_auth = bool(self.env.get("AI_GATEWAY_API_KEY") or self.env.get("VERCEL_OIDC_TOKEN"))
        self.results["live_model"] = {
            "status": "NOT_RUN" if has_auth else "BLOCKED",
            "reason": "Live model evaluation not requested" if has_auth else "No model gateway credential configured",
            "model_quality_measured": False,
        }
        if include_live and has_auth:
            from graphos.worker import build_once, verify_once
            def live() -> dict:
                run_id, _ = self.create()
                model_names = ("AI_GATEWAY_API_KEY", "VERCEL_OIDC_TOKEN", "GRAPHOS_MODEL",
                               "GRAPHOS_BUILD_RESERVATION", "GRAPHOS_MAX_OUTPUT_TOKENS",
                               "GRAPHOS_MODEL_INPUT_MICRODOLLARS_PER_MILLION",
                               "GRAPHOS_MODEL_OUTPUT_MICRODOLLARS_PER_MILLION")
                with patch.dict(os.environ, {name: self.env[name] for name in model_names if name in self.env}):
                    build = build_once(self.api_url, self.tokens["builder"], run_id,
                                       builder="eve", worker_id="live-builder")
                assert build["status"] == "submitted", "Live model build did not submit an artifact"
                verified = verify_once(self.api_url, self.tokens["verifier"], run_id, worker_id="live-verifier")
                return {"status": "PASS" if verified["passed"] else "FAIL",
                        "run_id": run_id, "passed": verified["passed"], "provenance": build.get("provenance"),
                        "verifier_report": verified["report"], "quality_estimate": None}
            result = self.run_case("live_model_single_attempt", live)
            self.results["live_model"] = result
        self.results["finished_at"] = utcnow()
        self.results["summary"] = {status.lower(): sum(case["status"] == status for case in self.results["cases"])
                                   for status in ("PASS", "FAIL", "NOT_RUN", "BLOCKED")}
        reports = [case.get("details", {}).get("verifier_report", {}) for case in self.results["cases"]]
        self.results["coverage"] = {
            "configured_fixture_cases": len(cases),
            "browser_reports_with_image_identity": sum(bool(report.get("image_id")) for report in reports),
            "verifier_image_ids": sorted({report["image_id"] for report in reports if report.get("image_id")}),
            "suite_hash": self.profile["suite_hash"] if self.profile else None,
            "policy_hash": self.profile["policy_hash"] if self.profile else None,
            "controller_restart_requested": self.restart_controller is not None,
            "database_disaster_recovery_tested": False,
            "real_external_effects_tested": False,
            "statistical_model_benchmark_completed": False,
        }
        return self.results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=os.environ.get("GRAPHOS_API_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--managed", action="store_true", help="Launch API subprocess and test its restart")
    parser.add_argument("--live", action="store_true", help="Additionally attempt real model generation when authenticated")
    parser.add_argument("--output", type=Path, default=ROOT / "evals" / "results" / "acceptance.json")
    args = parser.parse_args()
    env = local_environment()
    required = [f"GRAPHOS_{role}_TOKEN" for role in ("OPERATOR", "BUILDER", "VERIFIER")]
    required.append("GRAPHOS_VERIFIER_IMAGE_DIGEST")
    if args.managed:
        required.extend(("GRAPHOS_DATABASE_URL", "GRAPHOS_ARTIFACT_ROOT"))
    missing = [name for name in required if not env.get(name)]
    if missing:
        parser.error("Missing configuration names: " + ", ".join(missing))
    server = ManagedAPI(env) if args.managed else None
    harness = None
    try:
        if server:
            server.start()
        harness = AcceptanceHarness(server.url if server else args.api_url, env,
                                    server.restart if server else None)
        results = harness.run_all(include_live=args.live)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(results, indent=2) + "\n")
        print(json.dumps({"output": str(args.output), "summary": results["summary"],
                          "live_model_status": results["live_model"]["status"]}))
        return 1 if results["summary"]["fail"] else 0
    finally:
        if harness:
            harness.close()
        if server:
            server.close()


if __name__ == "__main__":
    raise SystemExit(main())
