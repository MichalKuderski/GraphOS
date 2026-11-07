"""Operator CLI; commands are explicit and credentials never appear in output."""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import uuid

import httpx

from .transport import WorkerError, validate_api_url


def load_env(path: Path) -> None:
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ValueError("Invalid environment file; expected KEY=value without shell expressions")
        os.environ.setdefault(key, value)


def client(role: str = "operator") -> httpx.Client:
    token = os.environ.get(f"GRAPHOS_{role.upper()}_TOKEN", "")
    if not token:
        raise ValueError(f"GRAPHOS_{role.upper()}_TOKEN is not configured")
    base_url = validate_api_url(os.environ.get("GRAPHOS_API_URL", "http://127.0.0.1:8000"))
    return httpx.Client(base_url=base_url,
                        headers={"Authorization": f"Bearer {token}"}, timeout=30,
                        trust_env=False, follow_redirects=False)


def checked(response: httpx.Response):
    if response.is_error:
        # Never dump request headers or raw provider responses.
        try:
            detail = response.json().get("detail", "Request rejected")
        except ValueError:
            detail = "Request rejected"
        raise ValueError(f"HTTP {response.status_code}: {detail}")
    return response.json()


def new_run(name: str, budget: int):
    from .profiles import default_spec
    spec = default_spec()
    spec["name"] = name
    with client() as api:
        return checked(api.post("/v1/runs", json={"spec": spec, "budget": budget,
                                                 "idempotency_key": str(uuid.uuid4())}))


def execute(run_id: str, mode: str, reservation: int) -> dict:
    from .worker import build_once, verify_once
    url = os.environ.get("GRAPHOS_API_URL", "http://127.0.0.1:8000")
    builder_token = os.environ.get("GRAPHOS_BUILDER_TOKEN", "")
    verifier_token = os.environ.get("GRAPHOS_VERIFIER_TOKEN", "")
    if not builder_token or not verifier_token:
        raise ValueError("Both worker role credentials are required")
    with client() as api:
        initial = checked(api.get(f"/v1/runs/{run_id}"))
    blocked = _blocked_run_result(run_id, mode, initial)
    if blocked:
        return blocked
    bound = max(1, len(initial["tasks"]) * initial["spec"].get("max_attempts", 3) * 2 + 1)
    for _ in range(bound):
        build_once(url, builder_token, run_id, builder=mode, worker_id="cli-builder",
                   reserve=(1 if mode == "fixture" else reservation))
        # A live failure can pause the run. Read that state before claiming a
        # verifier, so the CLI reports reconciliation rather than a rejected call.
        with client() as api:
            after_build = checked(api.get(f"/v1/runs/{run_id}"))
        blocked = _blocked_run_result(run_id, mode, after_build)
        if blocked:
            return blocked
        verify_once(url, verifier_token, run_id, worker_id="cli-verifier")
        with client() as api:
            run = checked(api.get(f"/v1/runs/{run_id}"))
            if run["state"] in {"READY_FOR_RELEASE", "RELEASED"}:
                release = checked(api.get(f"/v1/runs/{run_id}/release"))
                return {"run_id": run_id, "state": "RELEASED", "builder_mode": mode,
                        "spent_microdollars": run["spent"], "release": release}
            blocked = _blocked_run_result(run_id, mode, run)
            if blocked:
                return blocked
        if any(t["state"] in {"BUILDING", "VERIFYING"} for t in run["tasks"]):
            return {"run_id": run_id, "state": "WAITING_FOR_LEASE", "accepted": False,
                    "detail": "Another or interrupted worker owns a lease; resume after expiry"}
    return {"run_id": run_id, "state": "EXECUTION_LIMIT", "accepted": False}


def _blocked_run_result(run_id: str, mode: str, run: dict) -> dict | None:
    if run["state"] not in {"EXHAUSTED", "CANCELLED", "BUDGET_EXCEEDED", "RECONCILIATION_REQUIRED"}:
        return None
    result = {"run_id": run_id, "state": run["state"], "builder_mode": mode,
              "spent_microdollars": run["spent"], "accepted": False}
    if run["state"] == "RECONCILIATION_REQUIRED":
        result["detail"] = "Provider cost reconciliation required; automatic retry blocked"
    return result


def _publish_directory(staged: Path, destination: Path) -> None:
    """Atomically publish without replacing a concurrently created destination."""
    # POSIX rename can overwrite an empty directory. Linux renameat2 supplies the
    # no-replace guarantee required by this Linux deployment's export operation.
    rename = getattr(ctypes.CDLL(None, use_errno=True), "renameat2", None)
    if rename is None:
        raise ValueError("Atomic no-replace export requires Linux renameat2 support")
    rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(staged), -100, os.fsencode(destination), 1):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(destination))


def export_release(run_id: str, destination: Path) -> dict:
    """Export one immutable release snapshot, never a later mutable run view."""
    from .artifacts import bundle_digest, materialize_files, validate_digest, validate_files
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("Export destination must not exist")
    with client() as api:
        release = checked(api.get(f"/v1/runs/{run_id}/release"))
        fields = ("run_id", "revision", "spec_hash", "profile", "tasks")
        if not isinstance(release, dict) or not all(field in release for field in fields):
            raise ValueError("Release manifest is incomplete")
        if release["run_id"] != run_id or type(release["revision"]) is not int or release["revision"] < 1:
            raise ValueError("Release manifest belongs to a different run or invalid revision")
        validate_digest(release["spec_hash"])
        manifest_hash = validate_digest(release.get("manifest_hash"))
        # This is the ledger's canonical JSON encoding; API delivery annotations
        # and release_id are deliberately outside the hashed manifest core.
        encoded = json.dumps({field: release[field] for field in fields}, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode()
        if hashlib.sha256(encoded).hexdigest() != manifest_hash:
            raise ValueError("Release manifest failed content verification")
        tasks = release["tasks"]
        if not isinstance(tasks, list) or not 1 <= len(tasks) <= 256:
            raise ValueError("Release manifest has no valid task bindings")
        bundles = []
        names = set()
        for task in tasks:
            if not isinstance(task, dict):
                raise ValueError("Release task binding is invalid")
            key = task.get("task_key")
            if (not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", key)
                    or key.casefold() in names or key.casefold() == "release.json"):
                raise ValueError("Release task key is unsafe or duplicated")
            validate_files({key + "/placeholder": ""})
            names.add(key.casefold())
            digest = validate_digest(task.get("candidate_hash"))
            downloaded = checked(api.get(f"/v1/artifacts/{digest}"))
            if (not isinstance(downloaded, dict) or downloaded.get("manifest_hash") != digest
                    or bundle_digest(downloaded.get("files")) != digest):
                raise ValueError("Downloaded artifact digest does not match release")
            bundles.append((key, downloaded["files"]))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".graphos-export-", dir=destination.parent) as temporary:
        staged = Path(temporary)
        for key, files in bundles:
            materialize_files(files, staged / key)
        (staged / "release.json").write_text(json.dumps(release, indent=2), encoding="utf-8")
        _publish_directory(staged, destination)
    return {"exported": str(destination.resolve()), "tasks": len(bundles),
            "run_id": run_id, "revision": release["revision"], "manifest_hash": manifest_hash}


def doctor() -> dict:
    import subprocess
    from .config import Settings
    from .ledger import Ledger
    checks = {}
    try:
        settings = Settings.from_env()
        checks["role_configuration"] = "ready"
        Ledger(settings.database_url).list_runs()
        checks["postgresql"] = "ready"
    except Exception:
        checks["configuration_or_database"] = "not ready; run setup and migrate"
    try:
        result = subprocess.run(["docker", "--host=unix:///var/run/docker.sock", "image", "inspect",
                                 "--format", "{{.Id}}", os.environ.get("GRAPHOS_VERIFIER_IMAGE", "graphos-verifier:local")],
                                capture_output=True, timeout=10, text=True)
        checks["verifier_image"] = "ready" if result.returncode == 0 else "missing"
    except (OSError, subprocess.TimeoutExpired):
        checks["verifier_image"] = "unavailable"
    checks["model_credentials"] = "configured" if (os.environ.get("AI_GATEWAY_API_KEY") or
                                                      os.environ.get("VERCEL_OIDC_TOKEN")) else "not configured"
    checks["fixture_mode"] = "enabled" if os.environ.get("GRAPHOS_ALLOW_FIXTURE") == "1" else "disabled"
    checks["production_readiness"] = "not certified; see docs/production-readiness.md"
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(prog="graphos")
    parser.add_argument("--env-file", type=Path, help="Load a private KEY=value file; never evaluated as shell")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    sub.add_parser("migrate")
    sub.add_parser("doctor")
    submit = sub.add_parser("submit")
    submit.add_argument("--name", default="GraphOS task-list application")
    submit.add_argument("--budget", type=int, default=1_000_000, help="Maximum microdollars")
    run = sub.add_parser("execute")
    run.add_argument("run_id")
    run.add_argument("--builder", choices=["fixture", "eve"], required=True)
    run.add_argument("--reservation", type=int, default=1_000_000)
    demo = sub.add_parser("demo")
    demo.add_argument("--builder", choices=["fixture", "eve"], required=True)
    demo.add_argument("--budget", type=int, default=1_000_000)
    demo.add_argument("--reservation", type=int, default=1_000_000)
    export = sub.add_parser("export")
    export.add_argument("run_id")
    export.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        if args.env_file:
            load_env(args.env_file)
        if args.command == "serve":
            if args.host not in {"127.0.0.1", "localhost", "::1"} and os.environ.get("GRAPHOS_ALLOW_REMOTE") != "1":
                raise ValueError("Remote binding requires GRAPHOS_ALLOW_REMOTE=1 and a TLS/auth deployment review")
            import uvicorn
            uvicorn.run("graphos.api:create_app", factory=True, host=args.host, port=args.port,
                        access_log=False, timeout_keep_alive=5, limit_concurrency=64)
            return
        if args.command == "migrate":
            from .config import Settings
            from .ledger import Ledger
            Ledger(Settings.from_env().database_url).migrate()
            value = {"migrations": "applied"}
        elif args.command == "doctor":
            value = doctor()
        elif args.command == "submit":
            r = new_run(args.name, args.budget)
            value = {"run_id": r["id"], "state": r["state"]}
        elif args.command == "execute":
            value = execute(args.run_id, args.builder, args.reservation)
        elif args.command == "demo":
            r = new_run("GraphOS verified task-list demonstration", args.budget)
            value = execute(r["id"], args.builder, args.reservation)
        elif args.command == "export":
            value = export_release(args.run_id, args.destination)
        print(json.dumps(value, indent=2, default=str))
    except WorkerError:
        print(json.dumps({"error": "Worker request failed; inspect the run state and service configuration."}),
              file=sys.stderr)
        raise SystemExit(1) from None
    except (ValueError, httpx.HTTPError, OSError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
