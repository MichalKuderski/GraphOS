"""Profile boundaries and verifier provenance, without model or database calls.

API tests exercise real routing/validation with only the persistence seam mocked;
the separate PostgreSQL acceptance suite remains the integration authority.
"""
from copy import deepcopy
import json
import shutil
from unittest.mock import Mock, patch
import uuid

from fastapi.testclient import TestClient
import pytest

from graphos.api import create_app
from graphos.artifacts import bundle_digest
from graphos.config import Settings
from graphos import profiles
from graphos.profiles import ACTIVE_PROFILES, default_spec, fixture_files, get_profile
from graphos.sandbox import verify_bundle
from graphos.worker import build_once, verify_once


IMAGE = "sha256:" + "a" * 64


@pytest.fixture
def trusted_assets(tmp_path, monkeypatch):
    source = profiles.VERIFIER_ROOT
    verifier = tmp_path / "verifier"
    shutil.copytree(source, verifier, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    monkeypatch.setattr(profiles, "VERIFIER_ROOT", verifier)
    return verifier


def test_every_executed_verifier_asset_invalidates_all_profile_suites(trusted_assets):
    baseline = {name: get_profile(name) for name in ACTIVE_PROFILES}
    manifest = baseline["static-web"]["suite_manifest"]["files"]
    assert "trusted_runner.py" in manifest
    assert "task_checks.py" in manifest
    assert "notes_checks.py" in manifest
    assert "inventory_checks.py" in manifest
    # Every helper, engine asset, license/metadata file, and Dockerfile is bound.
    assert any(name.endswith(".js") for name in manifest)
    for relative in manifest:
        path = trusted_assets / relative
        original = path.read_bytes()
        try:
            path.write_bytes(original + b"\nprofile-binding-mutation\n")
            for name in ACTIVE_PROFILES:
                changed = get_profile(name)
                assert changed["suite_hash"] != baseline[name]["suite_hash"], (relative, name)
                assert changed["policy_hash"] == baseline[name]["policy_hash"]
        finally:
            path.write_bytes(original)


def test_added_removed_and_unsafe_assets_cannot_reuse_suite_identity(trusted_assets):
    before = get_profile("static-web")["suite_hash"]
    helper = trusted_assets / "new-helper.py"
    helper.write_text("VALUE = 1\n")
    assert get_profile("static-web")["suite_hash"] != before
    helper.unlink()
    assert get_profile("static-web")["suite_hash"] == before
    helper.symlink_to(trusted_assets / "trusted_runner.py")
    with pytest.raises(profiles.ProfileError, match="symlinks"):
        get_profile("static-web")


def test_cache_files_do_not_change_the_executed_asset_manifest(trusted_assets):
    before = get_profile("static-web")
    cache = trusted_assets / "__pycache__"
    cache.mkdir()
    (cache / "helper.cpython-312.pyc").write_bytes(b"unused host bytecode")
    after = get_profile("static-web")
    assert after["suite_hash"] == before["suite_hash"]
    assert after["suite_manifest"] == before["suite_manifest"]


def test_changed_helper_between_manifest_and_snapshot_blocks_container(trusted_assets, monkeypatch):
    monkeypatch.setenv("GRAPHOS_VERIFIER_IMAGE_DIGEST", IMAGE)
    profile = get_profile("local-notes")
    helper = trusted_assets / "notes_checks.py"
    helper.write_bytes(helper.read_bytes() + b"\n# changed after claim\n")
    with patch("graphos.sandbox.VERIFIER_ROOT", trusted_assets), \
         patch("graphos.sandbox.require_active", return_value=profile), \
         patch("graphos.sandbox.shutil.which", return_value="docker"), \
         patch("graphos.sandbox.run_bounded", return_value=(0, b"", b"")) as runner:
        result = verify_bundle(fixture_files("local-notes"), profile["acceptance_criteria"],
                               profile_id="local-notes")
    assert result["passed"] is False
    assert result["checks"][0]["name"] == "trusted_suite"
    assert all("run" not in call.args[0] and "inspect" not in call.args[0]
               for call in runner.call_args_list)


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHOS_VERIFIER_IMAGE_DIGEST", IMAGE)
    persistence = Mock()
    persistence.create_run.side_effect = lambda spec, budget, key: {
        "id": str(uuid.uuid4()), "spec": spec, "budget": budget}
    monkeypatch.setattr("graphos.api.Ledger", lambda _: persistence)
    settings = Settings("postgresql://unused/validation-only", tmp_path / "artifacts",
                        "o" * 32, "b" * 32, "v" * 32, allow_fixture=True)
    app = create_app(settings)
    # No lifespan/database initialization: only endpoint contract behavior is tested.
    client = TestClient(app)
    yield client, persistence, app.state.store
    client.close()


def admit(client, spec):
    return client.post("/v1/runs", headers={"Authorization": "Bearer " + "o" * 32},
                       json={"spec": spec, "budget": 100, "idempotency_key": uuid.uuid4().hex})


@pytest.mark.parametrize("name", ACTIVE_PROFILES)
def test_api_admits_each_registered_task_and_fills_only_its_criteria(api, name):
    client, persistence, _ = api
    spec = default_spec(name)
    spec["requirements"] = []
    response = admit(client, spec)
    assert response.status_code == 201, response.text
    value = response.json()
    assert value["spec"]["profile"] == name
    assert value["spec"]["requirements"] == get_profile(name)["acceptance_criteria"]
    assert value["evidence_current"] is True
    persistence.create_run.assert_called_once()


@pytest.mark.parametrize("name,other", [(a, b) for a in ACTIVE_PROFILES
                                       for b in ACTIVE_PROFILES if a != b])
def test_api_rejects_a_task_or_requirements_borrowed_from_another_profile(api, name, other):
    client, persistence, _ = api
    for field in ("tasks", "requirements"):
        spec = default_spec(name)
        spec[field] = default_spec(other)[field]
        response = admit(client, spec)
        assert response.status_code == 422, (field, response.text)
    persistence.create_run.assert_not_called()


def test_api_profile_listing_exposes_matching_templates_only_for_active_profiles(api):
    client, _, _ = api
    response = client.get("/v1/profiles", headers={"Authorization": "Bearer " + "o" * 32})
    assert response.status_code == 200
    items = {item["id"]: item for item in response.json()}
    assert set(ACTIVE_PROFILES) <= items.keys()
    for name in ACTIVE_PROFILES:
        assert items[name]["task_template"] == default_spec(name)["tasks"]
    for name in profiles.CONTRACT_ONLY:
        assert items[name]["status"] == "contract-only"
        assert "task_template" not in items[name]
        spec = default_spec()
        spec["profile"] = name
        assert admit(client, spec).status_code == 422


@pytest.mark.parametrize("defect", ["other-profile", "old-runner", "wrong-image", "stale-suite"])
def test_passing_evidence_requires_this_profile_runner_image_and_current_suite(api, defect):
    client, persistence, store = api
    spec = default_spec("local-notes")
    profile = get_profile("local-notes")
    run_id, task_id = str(uuid.uuid4()), str(uuid.uuid4())
    persistence.get_run.return_value = {"id": run_id, "spec": spec}
    candidate = store.put_bundle(fixture_files("local-notes"))
    report = {"passed": True, "checks": [{"name": name, "passed": True}
                                         for name in profile["required_checks"]],
              "suite_hash": profile["suite_hash"], "policy_hash": profile["policy_hash"],
              "runner": "docker-trusted-playwright-profiles-v2", "image_id": IMAGE}
    if defect == "other-profile":
        other = get_profile("local-inventory")
        report.update(suite_hash=other["suite_hash"],
                      checks=[{"name": name, "passed": True} for name in other["required_checks"]])
    elif defect == "old-runner":
        report["runner"] = "docker-trusted-playwright-static-web-v1"
    elif defect == "wrong-image":
        report["image_id"] = "sha256:" + "b" * 64
    else:
        report["suite_hash"] = "c" * 64
    payload = {"token": "lease", "epoch": 1, "revision": 1, "input_hash": "d" * 64,
               "candidate_hash": candidate, "suite_hash": profile["suite_hash"],
               "policy_hash": profile["policy_hash"], "passed": True, "report": report}
    response = client.post(f"/v1/runs/{run_id}/tasks/{task_id}/verify", json=payload,
                           headers={"Authorization": "Bearer " + "v" * 32})
    assert response.status_code == 422, response.text
    persistence.submit_verification.assert_not_called()


@pytest.mark.parametrize("name", ACTIVE_PROFILES)
def test_workers_dispatch_fixture_and_verification_to_the_claimed_profile(name):
    profile = get_profile(name)
    files = fixture_files(name)
    claim = {"task_id": "task", "task_key": "app", "token": "lease", "epoch": 1,
             "revision": 1, "input_hash": "d" * 64, "profile": name, "reservation": 1,
             "suite_hash": profile["suite_hash"], "policy_hash": profile["policy_hash"],
             "requirements": profile["acceptance_criteria"], "dependencies": {}}
    with patch("graphos.worker._request", side_effect=[deepcopy(claim), {"state": "SUBMITTED"}]) as request, \
         patch("graphos.worker._eve_build") as model:
        built = build_once("http://localhost:8000", "builder-token", "run", "fixture")
    assert built["status"] == "submitted"
    assert request.call_args.args[3]["files"] == files
    assert built["provenance"]["fixture"] == f"{name}-v{profile['version']}"
    model.assert_not_called()
    digest = bundle_digest(files)
    claim["candidate_hash"] = digest
    report = {"passed": False, "checks": [{"name": "synthetic-observation", "passed": False}]}
    with patch("graphos.worker._request", side_effect=[claim, {"manifest_hash": digest, "files": files}, {}]), \
         patch("graphos.worker.verify_bundle", return_value=report) as verifier:
        result = verify_once("http://localhost:8000", "verifier-token", "run")
    assert result["passed"] is False
    verifier.assert_called_once_with(files, profile["acceptance_criteria"], profile_id=name)


def test_each_profile_has_distinct_suite_and_fixture_identity():
    assert len({get_profile(name)["suite_hash"] for name in ACTIVE_PROFILES}) == len(ACTIVE_PROFILES)
    assert len({bundle_digest(fixture_files(name)) for name in ACTIVE_PROFILES}) == len(ACTIVE_PROFILES)
    # Input specs also retain their product identity despite a shared task key.
    assert len({json.dumps(default_spec(name), sort_keys=True) for name in ACTIVE_PROFILES}) == len(ACTIVE_PROFILES)
