"""Bounded Docker execution for the fixed trusted browser verifier."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import tempfile
import time
import uuid

from .artifacts import ArtifactError, materialize_files, validate_digest, validate_files
from .profiles import SANDBOX_POLICY, VERIFIER_ROOT, get_profile


class ProcessError(RuntimeError):
    pass


def run_bounded(command: list[str], *, timeout: float, output_limit: int,
                stdin: bytes | None = None, env: dict[str, str] | None = None,
                cwd: Path | None = None) -> tuple[int, bytes, bytes]:
    """No shell, bounded output and duration, with process-group cancellation."""
    with tempfile.TemporaryFile() as input_file:
        if stdin is not None:
            input_file.write(stdin)
            input_file.seek(0)
        process = subprocess.Popen(command, stdin=input_file, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, env=env, cwd=cwd,
                                   start_new_session=True)
        selector = selectors.DefaultSelector()
        streams = {"stdout": bytearray(), "stderr": bytearray()}
        for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, name)
        started = time.monotonic()
        total = 0
        try:
            while selector.get_map():
                remaining = timeout - (time.monotonic() - started)
                if remaining <= 0:
                    raise ProcessError("subprocess deadline exceeded")
                for key, _ in selector.select(min(remaining, 0.2)):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    total += len(chunk)
                    if total > output_limit:
                        raise ProcessError("subprocess output limit exceeded")
                    streams[key.data].extend(chunk)
            remaining = timeout - (time.monotonic() - started)
            try:
                code = process.wait(timeout=max(remaining, 0.001))
            except subprocess.TimeoutExpired as exc:
                raise ProcessError("subprocess deadline exceeded") from exc
            return code, bytes(streams["stdout"]), bytes(streams["stderr"])
        finally:
            selector.close()
            # The group may still contain descendants after its leader exits.
            # In particular they can keep a pipe open until this call times out.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            if process.poll() is None:
                process.wait(timeout=5)
            process.stdout.close()
            process.stderr.close()


def docker_command(image_id: str, candidate: Path, trusted_runner: Path,
                   container_name: str, *, docker_config: Path) -> list[str]:
    """All arguments are fixed policy or trusted local paths, never model commands."""
    policy = SANDBOX_POLICY
    clear_proxy = [part for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
                                     "http_proxy", "https_proxy", "all_proxy", "no_proxy")
                   for part in ("--env", name + "=")]
    return ["docker", "--host", "unix:///var/run/docker.sock", "--config", str(docker_config),
            "run", "--rm", "--name", container_name,
            "--network", "none", "--user", policy["user"], "--read-only",
            "--security-opt", "no-new-privileges", "--cap-drop", "ALL",
            "--pids-limit", str(policy["pids"]), "--cpus", policy["cpus"],
            "--memory", policy["memory"], "--memory-swap", policy["memory_swap"],
            "--shm-size", policy["shm_size"], "--tmpfs", policy["tmpfs"],
            "--mount", f"type=bind,src={candidate},dst=/candidate,readonly",
            "--mount", f"type=bind,src={trusted_runner},dst=/verifier/trusted_runner.py,readonly",
            *clear_proxy, "--workdir", "/tmp", "--entrypoint", "python", image_id,
            "-I", "/verifier/trusted_runner.py"]


def verify_bundle(files: dict[str, str], requirements: list[str]) -> dict:
    started = time.monotonic()
    profile = get_profile("static-web")
    image = os.environ.get("GRAPHOS_VERIFIER_IMAGE", "graphos-verifier:local")
    base = {"runner": "docker-trusted-playwright-static-web-v1",
            "suite_hash": profile["suite_hash"], "policy_hash": profile["policy_hash"],
            "image": image, "browser_process_sandbox": False}

    def failure(name: str, detail: str) -> dict:
        return {**base, "passed": False,
                "checks": [{"name": name, "passed": False, "detail": detail}],
                "duration_ms": round((time.monotonic() - started) * 1000)}

    try:
        validate_files(files)
    except ArtifactError as exc:
        return failure("artifact_validation", str(exc))
    if any(name not in files for name in profile["required_files"]):
        return failure("required_files", "index.html, app.js and styles.css are required")
    if requirements != profile["acceptance_criteria"]:
        return failure("profile_requirements", "This fixed suite cannot certify a different requirement set")
    expected_image = profile["sandbox_policy"]["image_digest"]
    try:
        if not isinstance(expected_image, str) or not expected_image.startswith("sha256:"):
            raise ArtifactError("missing image pin")
        validate_digest(expected_image[7:])
    except ArtifactError:
        return failure("sandbox_image_pin", "GRAPHOS_VERIFIER_IMAGE_DIGEST must pin the trusted local image")
    if shutil.which("docker") is None:
        return failure("sandbox_available", "Docker is unavailable; candidate execution was blocked")
    trusted = VERIFIER_ROOT / "trusted_runner.py"
    if trusted.is_symlink() or not trusted.is_file():
        return failure("trusted_suite", "Trusted runner is missing or unsafe")
    container_name = "graphos-verify-" + uuid.uuid4().hex
    temporary = tempfile.TemporaryDirectory(prefix="graphos-verify-")
    directory = Path(temporary.name)
    docker_config = directory / "docker-config"
    docker_config.mkdir(mode=0o700)
    docker_base = ["docker", "--host", "unix:///var/run/docker.sock", "--config", str(docker_config)]
    docker_env = {key: value for key, value in os.environ.items() if key in {"PATH", "LANG", "LC_ALL"}}
    try:
        suite_bytes = trusted.read_bytes()
        if hashlib.sha256(suite_bytes).hexdigest() != profile["suite_manifest"]["runner"]:
            return failure("trusted_suite", "Trusted suite changed before execution")
        trusted_copy = directory / "trusted_runner.py"
        trusted_copy.write_bytes(suite_bytes)
        trusted_copy.chmod(0o444)
        code, stdout, _ = run_bounded([*docker_base, "image", "inspect", "--format", "{{.Id}}", image],
                                      timeout=15, output_limit=65536, env=docker_env)
        image_id = stdout.decode("utf-8").strip()
        if code or not image_id.startswith("sha256:") or len(image_id) != 71:
            return failure("sandbox_available", "Configured verifier image is unavailable; build it first")
        if image_id != expected_image:
            return failure("sandbox_image_pin", "Verifier image differs from the policy's immutable digest")
        base["image_id"] = image_id
        candidate = directory / "candidate"
        materialize_files(files, candidate)
        command = docker_command(image_id, candidate, trusted_copy, container_name, docker_config=docker_config)
        code, stdout, stderr = run_bounded(command, timeout=SANDBOX_POLICY["timeout_seconds"],
                                           output_limit=SANDBOX_POLICY["stdout_stderr_limit"], env=docker_env)
        if code:
            detail = stderr.decode("utf-8", errors="replace")[-600:]
            return failure("sandbox_execution", f"Verifier container exited with code {code}: {detail}")
        try:
            report = json.loads(stdout)
        except (ValueError, UnicodeError):
            return failure("trusted_report", "Verifier did not return valid bounded JSON")
        checks = report.get("checks") if isinstance(report, dict) else None
        if (not isinstance(checks, list) or len(checks) > 32
                or any(not isinstance(c, dict) or type(c.get("passed")) is not bool
                       or not isinstance(c.get("name"), str) for c in checks)):
            return failure("trusted_report", "Verifier returned an invalid check schema")
        names = [c["name"] for c in checks]
        passed = (report.get("passed") is True and names == profile["required_checks"]
                  and all(c["passed"] for c in checks))
        return {**report, **base, "passed": passed,
                "duration_ms": round((time.monotonic() - started) * 1000)}
    except (OSError, ProcessError, ArtifactError) as exc:
        return failure("sandbox_execution", str(exc)[:300])
    finally:
        # Killing the Docker client does not guarantee the container stopped.
        try:
            run_bounded([*docker_base, "rm", "--force", container_name], timeout=10,
                        output_limit=65536, env=docker_env)
        except (OSError, ProcessError):
            pass
        temporary.cleanup()
