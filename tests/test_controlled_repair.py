"""Offline tests for the explicit controlled-fault experiment."""
import hashlib
import json
from unittest.mock import Mock

import pytest

from scripts import controlled_repair as repair

FILES = {"index.html": "<main>tasks</main>", "app.js": "// app", "styles.css": "body{}"}
HASH = "a" * 64


def write_seed(tmp_path, *, mode="eve", candidate_hash=None):
    key = "app"
    (tmp_path / key).mkdir()
    for name, value in FILES.items():
        (tmp_path / key / name).write_text(value)
    manifest = {"run_id": "source-run", "revision": 1, "spec_hash": HASH,
                "profile": "static-web", "tasks": [{"task_key": key,
                    "candidate_hash": candidate_hash or repair.bundle_digest(FILES),
                    "provenance": {"mode": mode}}]}
    manifest["manifest_hash"] = hashlib.sha256(json.dumps(manifest, sort_keys=True,
                                        separators=(",", ":")).encode()).hexdigest()
    (tmp_path / "release.json").write_text(json.dumps(manifest))
    return manifest


def context():
    binding = {"candidate_hash": repair.bundle_digest(FILES), "evidence_hash": HASH,
               "verifier_attempt_id": "v1", "input_hash": HASH, "revision": 1,
               "suite_hash": HASH, "policy_hash": HASH}
    feedback = {**binding, "files": dict(FILES),
                "checks": [{"name": "local_storage_reload", "passed": False, "detail": "missing storage"}]}
    return binding, {"repair": dict(binding)}, feedback


def test_valid_seed_requires_real_live_provenance_and_exact_bytes(tmp_path):
    expected = write_seed(tmp_path)
    manifest, files = repair.load_seed(tmp_path)
    assert manifest == expected and files == FILES
    (tmp_path / "app/app.js").write_text("// tampered")
    with pytest.raises(ValueError, match="candidate_hash_mismatch"):
        repair.load_seed(tmp_path)


@pytest.mark.parametrize("mode", ["fixture", "unknown", None])
def test_invalid_seed_never_constructs_live_services(tmp_path, monkeypatch, mode):
    write_seed(tmp_path, mode=mode)
    service = Mock()
    monkeypatch.setattr(repair, "LiveEve", service)
    with pytest.raises(ValueError, match="genuine_live_model_release"):
        repair.main([str(tmp_path), "--execute"])
    service.assert_not_called()


def test_missing_authorization_precedes_services(tmp_path, monkeypatch):
    service = Mock()
    monkeypatch.setattr(repair, "LiveEve", service)
    with pytest.raises(SystemExit):
        repair.main([str(tmp_path)])
    service.assert_not_called()


def test_seed_symlink_and_manifest_corruption_rejected(tmp_path):
    write_seed(tmp_path)
    target = tmp_path / "app/app.js"
    target.unlink()
    target.symlink_to(tmp_path / "app/styles.css")
    with pytest.raises(ValueError, match="symlinks_forbidden"):
        repair.load_seed(tmp_path)
    manifest = json.loads((tmp_path / "release.json").read_text())
    manifest["revision"] = 2
    (tmp_path / "release.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="manifest_mismatch"):
        repair.load_seed(tmp_path)


def test_guard_rejects_stale_or_wrong_diagnostics_without_model_charge():
    binding, claim, feedback = context()
    original, persist = Mock(), Mock()
    report = {"live_builds_dispatched": 0}
    guarded = repair.guarded_adapter(original, binding, report, persist)
    invalids = [None, {**feedback, "evidence_hash": "b" * 64},
                {**feedback, "verifier_attempt_id": "other"}, {**feedback, "revision": 2},
                {**feedback, "files": {**FILES, "app.js": "tampered"}},
                {**feedback, "checks": [{"name": "local_storage_reload", "passed": True}]}]
    for invalid in invalids:
        with pytest.raises(repair.worker.BuildFailure) as exc:
            guarded(claim, {}, [], invalid)
        assert exc.value.actual_cost == 0
    original.assert_not_called()
    persist.assert_not_called()
    assert report["live_builds_dispatched"] == 0


def test_guard_delegates_once_and_never_fabricates_output():
    binding, claim, feedback = context()
    original, persist = Mock(return_value={"actual_result": True}), Mock()
    report = {"live_builds_dispatched": 0}
    guarded = repair.guarded_adapter(original, binding, report, persist)
    assert guarded(claim, {"profile": True}, [], feedback) == {"actual_result": True}
    original.assert_called_once_with(claim, {"profile": True}, [], feedback)
    persist.assert_called_once()
    assert report["repair_bindings_checked_before_dispatch"] is True
    with pytest.raises(repair.worker.BuildFailure) as exc:
        guarded(claim, {}, [], feedback)
    assert exc.value.actual_cost == 0
    assert original.call_count == report["live_builds_dispatched"] == 1


def test_build_summary_excludes_credentials_and_preserves_receipt_ids():
    summary = repair.summarize_build({"status": "submitted", "claim": {"token": "NEVER_LOG", "task_id": "task"},
        "provenance": {"mode": "eve", "model": "model", "secret": "NEVER_LOG"},
        "usage": {"actual_cost_microdollars": 1, "generations": [{"generation_id": "receipt"}], "secret": "NEVER_LOG"}})
    assert "NEVER_LOG" not in json.dumps(summary)
    assert summary["usage"]["generations"] == [{"generation_id": "receipt"}]
