"""Declared execution profiles; unsupported domains fail closed."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from .artifacts import ArtifactError, canonical, validate_files

def _runtime_root() -> Path:
    override = os.environ.get("GRAPHOS_RUNTIME_ROOT")
    configured = Path(override) if override else Path(__file__).resolve().parents[1]
    if not configured.is_absolute():
        raise RuntimeError("GRAPHOS_RUNTIME_ROOT must be an absolute trusted deployment directory")
    root = configured.resolve()
    if not root.is_dir() or any(not (root / name).is_dir() for name in ("profiles", "verifier")):
        raise RuntimeError("GraphOS runtime assets are missing; set GRAPHOS_RUNTIME_ROOT to the trusted checkout or deployment root")
    return root


ROOT = _runtime_root()
PROFILE_ROOT = ROOT / "profiles"
VERIFIER_ROOT = ROOT / "verifier"
SANDBOX_POLICY = {
    "version": 1,
    "network": "none",
    "user": "10001:10001",
    "read_only": True,
    "no_new_privileges": True,
    "capabilities": [],
    "pids": 128,
    "cpus": "1.0",
    "memory": "768m",
    "memory_swap": "768m",
    "shm_size": "128m",
    "tmpfs": "/tmp:rw,nosuid,nodev,size=128m",
    "timeout_seconds": 90,
    "stdout_stderr_limit": 1024 * 1024,
    "playwright_version": "1.64.1",
    "candidate_execution": "chromium-in-docker-only",
    "browser_process_sandbox": False,
    "docker_host": "unix:///var/run/docker.sock",
    "docker_config": "fresh-empty-per-verification",
    "container_proxy_environment": "cleared",
}
CONTRACT_ONLY = {
    "games": "Needs engine-specific build, playability, asset, and performance checks.",
    "bots": "Needs a platform adapter, scoped credentials, event replay, and rate-limit checks.",
    "data": "Needs dataset provenance, schema/grain validation, and reproducible analytical checks.",
    "media": "Needs modality-specific quality, timing, provenance, and rights checks.",
    "trading-research": "Research-only future profile; requires leakage, costs, walk-forward, and risk validation. No live trading capability.",
}


class ProfileError(ValueError):
    pass


def sandbox_policy() -> dict:
    return {**SANDBOX_POLICY, "image_digest": os.environ.get("GRAPHOS_VERIFIER_IMAGE_DIGEST")}


def get_profile(name: str) -> dict:
    if name == "static-web":
        profile_bytes = (PROFILE_ROOT / name / "profile.json").read_bytes()
        profile = json.loads(profile_bytes)
        suite_manifest = {
            "profile": hashlib.sha256(profile_bytes).hexdigest(),
            "runner": hashlib.sha256((VERIFIER_ROOT / "trusted_runner.py").read_bytes()).hexdigest(),
            "dockerfile": hashlib.sha256((VERIFIER_ROOT / "Dockerfile").read_bytes()).hexdigest(),
            "playwright_version": SANDBOX_POLICY["playwright_version"],
        }
        profile["suite_hash"] = hashlib.sha256(canonical(suite_manifest)).hexdigest()
        profile["suite_manifest"] = suite_manifest
        policy = sandbox_policy()
        profile["policy_hash"] = hashlib.sha256(canonical(policy)).hexdigest()
        profile["sandbox_policy"] = policy
        return profile
    if name in CONTRACT_ONLY:
        contract = {"id": name, "status": "contract-only", "version": 1,
                    "description": CONTRACT_ONLY[name], "required_files": [],
                    "acceptance_criteria": [], "execution_enabled": False}
        contract["suite_hash"] = hashlib.sha256(canonical(contract)).hexdigest()
        contract["policy_hash"] = hashlib.sha256(canonical({"execution": "blocked", "id": name})).hexdigest()
        return contract
    raise ProfileError("unknown execution profile")


def list_profiles() -> list[dict]:
    return [get_profile(name) for name in ("static-web", *CONTRACT_ONLY)]


def default_spec() -> dict:
    profile = get_profile("static-web")
    return {"name": "Accessible task list", "profile": "static-web",
            "requirements": list(profile["acceptance_criteria"]),
            "tasks": [{"key": "app", "objective": "Build a polished task-list app satisfying every fixed static-web profile requirement.",
                       "depends_on": []}],
            "suite_hash": profile["suite_hash"], "policy_hash": profile["policy_hash"],
            "max_attempts": 3}


def require_active(name: str) -> dict:
    profile = get_profile(name)
    if profile["status"] != "active":
        raise ProfileError(f"profile {name!r} is contract-only and cannot execute")
    return profile


def fixture_files() -> dict[str, str]:
    """Explicit deterministic integration fixture; never called as an auth fallback."""
    directory = PROFILE_ROOT / "static-web" / "fixtures" / "task-list"
    result = {}
    for name in ("index.html", "app.js", "styles.css"):
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ArtifactError("fixture contains an unsafe file")
        result[name] = path.read_text(encoding="utf-8")
    validate_files(result)
    return result
