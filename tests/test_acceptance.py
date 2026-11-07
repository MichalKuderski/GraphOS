"""Real HTTP/PostgreSQL/Docker integration; deliberately separate from unit tests."""
import json
from pathlib import Path

import pytest

from scripts.acceptance import AcceptanceHarness, ManagedAPI, local_environment

pytestmark = [pytest.mark.integration, pytest.mark.sandbox]


@pytest.fixture(scope="module")
def acceptance_results():
    env = local_environment()
    required = ("GRAPHOS_DATABASE_URL", "GRAPHOS_ARTIFACT_ROOT", "GRAPHOS_OPERATOR_TOKEN",
                "GRAPHOS_BUILDER_TOKEN", "GRAPHOS_VERIFIER_TOKEN", "GRAPHOS_VERIFIER_IMAGE_DIGEST")
    missing = [name for name in required if not env.get(name)]
    if missing:
        pytest.skip("Real integration configuration unavailable: " + ", ".join(missing))
    server = ManagedAPI(env)
    harness = None
    try:
        server.start()
        harness = AcceptanceHarness(server.url, env, server.restart)
        results = harness.run_all()
        destination = Path(__file__).resolve().parents[1] / "evals" / "results" / "pytest-acceptance.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(results, indent=2) + "\n")
        yield {case["id"]: case for case in results["cases"]}
    finally:
        if harness:
            harness.close()
        server.close()


@pytest.mark.parametrize("case", [
    "happy_fixture_release",
    "duplicate_admission_and_submission",
    "registered_profile_boundary",
    "roles_and_cancellation",
    "evidence_revision_and_artifact_binding",
    "bad_candidate_fails_browser",
    "worker_crash_and_lease_recovery",
    "controller_restart_preserves_state",
])
def test_http_acceptance_contract(acceptance_results, case):
    result = acceptance_results[case]
    assert result["status"] == "PASS", result
