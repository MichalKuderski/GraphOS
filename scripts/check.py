"""Run all mandatory local gates; skipped integration checks are not success."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from graphos.__main__ import load_env  # noqa: E402


def source_digest():
    paths = [ROOT / "pyproject.toml", ROOT / "requirements.lock"]
    for folder in ("graphos", "profiles", "verifier", "scripts", "tests", "docs/foundation/reference"):
        paths.extend(path for path in (ROOT / folder).rglob("*")
                     if path.is_file() and "__pycache__" not in path.parts)
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(str(path.relative_to(ROOT)).encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def main():
    if (ROOT / ".state/local.env").exists():
        load_env(ROOT / ".state/local.env")
    required = ("GRAPHOS_TEST_DATABASE_URL", "GRAPHOS_DATABASE_URL", "GRAPHOS_ARTIFACT_ROOT",
                "GRAPHOS_OPERATOR_TOKEN", "GRAPHOS_BUILDER_TOKEN", "GRAPHOS_VERIFIER_TOKEN",
                "GRAPHOS_VERIFIER_IMAGE_DIGEST")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise SystemExit("Mandatory integration configuration missing: " + ", ".join(missing))
    output = ROOT / "evals/results"
    output.mkdir(parents=True, exist_ok=True)
    report = {"status": "RUNNING", "started_at": datetime.now(timezone.utc).isoformat(),
              "source_digest": source_digest(), "commands": [],
              "model_generation": "not exercised by this pipeline", "production_certification": False}
    destination = output / "checks.json"
    destination.write_text(json.dumps(report, indent=2) + "\n")
    commands = [
        [sys.executable, "-m", "ruff", "check", "graphos", "tests", "scripts", "verifier"],
        [sys.executable, "-m", "unittest", "discover", "-s", "docs/foundation/reference", "-q"],
        [sys.executable, "-m", "pytest", "-q", "--junitxml", str(output / "pytest.xml")],
    ]
    for command in commands:
        result = subprocess.run(command, cwd=ROOT, check=False)
        report["commands"].append({"command": command, "exit_code": result.returncode})
        if result.returncode:
            report.update(status="FAIL", finished_at=datetime.now(timezone.utc).isoformat())
            destination.write_text(json.dumps(report, indent=2) + "\n")
            raise SystemExit(result.returncode)
    suite = ET.parse(output / "pytest.xml").getroot()
    counts = {key: sum(int(s.get(key, 0)) for s in suite.iter("testsuite"))
              for key in ("tests", "failures", "errors", "skipped")}
    report.update(python=counts, original_reference_tests=25,
                  finished_at=datetime.now(timezone.utc).isoformat(),
                  source_unchanged=source_digest() == report["source_digest"])
    report["status"] = "PASS" if not counts["skipped"] and report["source_unchanged"] else "INCOMPLETE"
    destination.write_text(json.dumps(report, indent=2) + "\n")
    if report["status"] != "PASS":
        raise SystemExit("Mandatory checks skipped or source changed during verification; rerun before promotion")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
