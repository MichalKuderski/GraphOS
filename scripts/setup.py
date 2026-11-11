"""Reproducible local setup. Creates private secrets; never prints their values."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
PG_IMAGE = "postgres:17-bookworm@sha256:665dc7b37ac52a17e298511414c21d23ffa4e6a6ef6225b3e5d59c7afb35e994"


def command(args, **kwargs):
    return subprocess.run(args, check=True, cwd=ROOT, **kwargs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-agent", action="store_true", help="Install and build the real eve adapter (no model calls)")
    args = parser.parse_args()
    if sys.version_info < (3, 12):
        raise SystemExit("Python 3.12 or newer is required")
    state = ROOT / ".state"
    state.mkdir(mode=0o700, exist_ok=True)
    env_path = state / "local.env"
    if not env_path.exists():
        password = secrets.token_urlsafe(32)
        values = {
            "GRAPHOS_DATABASE_URL": f"postgresql://graphos:{password}@127.0.0.1:55432/graphos",
            "GRAPHOS_TEST_DATABASE_URL": f"postgresql://graphos:{password}@127.0.0.1:55432/graphos",
            "GRAPHOS_ARTIFACT_ROOT": str(state / "artifacts"),
            "GRAPHOS_OPERATOR_TOKEN": secrets.token_urlsafe(48),
            "GRAPHOS_BUILDER_TOKEN": secrets.token_urlsafe(48),
            "GRAPHOS_VERIFIER_TOKEN": secrets.token_urlsafe(48),
            "GRAPHOS_EVE_TOKEN": secrets.token_urlsafe(48),
            "EVE_SERVER_URL": "http://127.0.0.1:3001",
            "GRAPHOS_API_URL": "http://127.0.0.1:8030",
            "GRAPHOS_ALLOW_FIXTURE": "1",
            "GRAPHOS_VERIFIER_IMAGE": "graphos-verifier:local",
            "GRAPHOS_SESSION_BUDGET_MICRODOLLARS": "5000000",
        }
        env_path.write_text("".join(f"{k}={v}\n" for k,v in values.items()))
        env_path.chmod(0o600)
        db_path = state / "postgres.env"
        db_path.write_text(f"POSTGRES_USER=graphos\nPOSTGRES_PASSWORD={password}\nPOSTGRES_DB=graphos\n")
        db_path.chmod(0o600)
    py = ROOT / ".venv/bin/python"
    if not py.exists():
        command([sys.executable, "-m", "venv", str(ROOT / ".venv")])
    command([str(py), "-m", "pip", "install", "-r", "requirements.lock", "--disable-pip-version-check"])
    command([str(py), "-m", "pip", "install", "--no-deps", "-e", ".", "--disable-pip-version-check"])
    env = os.environ.copy()
    for key in ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
        env.pop(key, None)
    docker = ["docker", "--host=unix:///var/run/docker.sock"]
    command(docker + ["info", "--format", "{{.ServerVersion}}"], env=env)
    exists = subprocess.run(docker + ["inspect", "--format", "{{.State.Running}}", "graphos-dev-db"],
                            env=env, capture_output=True, text=True)
    if exists.returncode:
        command(docker + ["run", "-d", "--name", "graphos-dev-db", "--env-file", str(state / "postgres.env"),
                          "-p", "127.0.0.1:55432:5432", "--mount",
                          "type=volume,source=graphos-dev-pgdata,target=/var/lib/postgresql/data", PG_IMAGE], env=env)
    elif exists.stdout.strip() != "true":
        command(docker + ["start", "graphos-dev-db"], env=env)
    for _ in range(30):
        ready = subprocess.run(docker + ["exec", "graphos-dev-db", "pg_isready", "-U", "graphos", "-d", "graphos"],
                               env=env, capture_output=True)
        if ready.returncode == 0:
            break
        time.sleep(1)
    else:
        raise SystemExit("PostgreSQL did not become ready; retained data was not deleted")
    build = docker + ["build", "-t", "graphos-verifier:local"]
    if env.get("CODEX_PROXY_CERT"):
        build += ["--secret", "id=proxy_ca,src=" + env["CODEX_PROXY_CERT"]]
    command(build + ["verifier"], env=env)
    digest = command(docker + ["image", "inspect", "--format", "{{.Id}}", "graphos-verifier:local"],
                     env=env, capture_output=True, text=True).stdout.strip()
    lines = [line for line in env_path.read_text().splitlines() if not line.startswith("GRAPHOS_VERIFIER_IMAGE_DIGEST=")]
    replacement = state / "local.env.next"
    with replacement.open("w", opener=lambda path, flags: os.open(path, flags, 0o600)) as out:
        out.write("\n".join(lines) + "\nGRAPHOS_VERIFIER_IMAGE_DIGEST=" + digest + "\n")
        out.flush()
        os.fsync(out.fileno())
    replacement.chmod(0o600)
    replacement.replace(env_path)
    command([str(py), "-m", "graphos", "--env-file", str(env_path), "migrate"])
    if args.with_agent:
        node_env = {**os.environ, "npm_config_cache": str(state / "npm-cache")}
        subprocess.run(["npm", "ci"], cwd=ROOT / "agents/eve", env=node_env, check=True)
        subprocess.run(["npm", "run", "build"], cwd=ROOT / "agents/eve", env=node_env, check=True)
    print(json.dumps({"setup": "complete", "credentials": ".state/local.env (private)",
                      "next": ".venv/bin/python -m graphos --env-file .state/local.env serve --port 8030",
                      "model_calls": "not made"}))


if __name__ == "__main__":
    main()
