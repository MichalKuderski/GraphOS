import hashlib
import json
from unittest.mock import patch

import httpx
import pytest

from graphos.__main__ import _publish_directory, client, execute, export_release, main
from graphos.artifacts import bundle_digest
from graphos.transport import WorkerError, validate_api_url


def release_for(files):
    core = {"run_id": "example-run", "revision": 1, "spec_hash": "a" * 64,
            "profile": "static-web", "tasks": [{"task_key": "app", "task_id": "task-1",
                                                  "candidate_hash": bundle_digest(files),
                                                  "evidence_hash": "b" * 64}]}
    digest = hashlib.sha256(json.dumps(core, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {**core, "manifest_hash": digest, "release_id": "release-1", "deployment_performed": False}


def api_client(handler):
    return httpx.Client(base_url="http://test", transport=httpx.MockTransport(handler))


def test_export_uses_only_release_snapshot_even_if_current_run_changes(tmp_path):
    original = {"index.html": "<h1>Released revision one</h1>"}
    revised = {"index.html": "<h1>Unverified revision two</h1>"}
    release = release_for(original)
    candidate = release["tasks"][0]["candidate_hash"]
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path == "/v1/runs/example-run/release":
            return httpx.Response(200, json=release)
        if request.url.path == f"/v1/artifacts/{candidate}":
            return httpx.Response(200, json={"manifest_hash": candidate, "files": original})
        if request.url.path == "/v1/runs/example-run":
            # This mutable view is deliberately newer and must never be consulted.
            return httpx.Response(200, json={"revision": 2, "tasks": [{"task_key": "app",
                                       "candidate_hash": bundle_digest(revised)}]})
        raise AssertionError(f"Unexpected download: {request.url.path}")

    destination = tmp_path / "delivered"
    with patch("graphos.__main__.client", side_effect=lambda: api_client(handler)):
        result = export_release("example-run", destination)
    assert paths == ["/v1/runs/example-run/release", f"/v1/artifacts/{candidate}"]
    assert (destination / "app/index.html").read_text() == original["index.html"]
    assert json.loads((destination / "release.json").read_text()) == release
    assert result["revision"] == 1 and result["manifest_hash"] == release["manifest_hash"]


def test_export_content_mismatch_leaves_no_delivered_or_partial_directory(tmp_path):
    original = {"index.html": "original"}
    release = release_for(original)
    candidate = release["tasks"][0]["candidate_hash"]

    def handler(request):
        if request.url.path.endswith("/release"):
            return httpx.Response(200, json=release)
        return httpx.Response(200, json={"manifest_hash": candidate, "files": {"index.html": "changed"}})

    destination = tmp_path / "delivered"
    with patch("graphos.__main__.client", side_effect=lambda: api_client(handler)):
        with pytest.raises(ValueError, match="does not match release"):
            export_release("example-run", destination)
    assert not destination.exists()
    assert list(tmp_path.iterdir()) == []


def test_export_tampered_release_is_rejected_before_artifact_download(tmp_path):
    release = release_for({"index.html": "original"})
    release["tasks"][0]["candidate_hash"] = "c" * 64
    paths = []

    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200, json=release)

    with patch("graphos.__main__.client", side_effect=lambda: api_client(handler)):
        with pytest.raises(ValueError, match="manifest failed"):
            export_release("example-run", tmp_path / "delivered")
    assert paths == ["/v1/runs/example-run/release"]
    assert list(tmp_path.iterdir()) == []


def test_atomic_publication_does_not_replace_concurrent_destination(tmp_path):
    staged = tmp_path / "staged"
    staged.mkdir()
    (staged / "candidate").write_text("candidate")
    destination = tmp_path / "concurrently-created"
    destination.mkdir()  # Even an empty directory must not be replaced.
    with pytest.raises(FileExistsError):
        _publish_directory(staged, destination)
    assert destination.is_dir() and list(destination.iterdir()) == []
    assert (staged / "candidate").read_text() == "candidate"


def test_execute_reports_recorded_release_state(monkeypatch):
    monkeypatch.setenv("GRAPHOS_BUILDER_TOKEN", "builder")
    monkeypatch.setenv("GRAPHOS_VERIFIER_TOKEN", "verifier")
    run = {"state": "READY_FOR_RELEASE", "tasks": [{"state": "ACCEPTED"}],
           "spec": {"max_attempts": 1}, "spent": 0}
    release = release_for({"index.html": "original"})

    def handler(request):
        return httpx.Response(200, json=release if request.url.path.endswith("/release") else run)

    with patch("graphos.__main__.client", side_effect=lambda: api_client(handler)), \
         patch("graphos.worker.build_once"), patch("graphos.worker.verify_once"):
        result = execute("example-run", "fixture", 1)
    assert result["state"] == "RELEASED"
    assert result["release"] == release


def test_execute_does_not_dispatch_an_already_paused_run(monkeypatch):
    monkeypatch.setenv("GRAPHOS_BUILDER_TOKEN", "builder")
    monkeypatch.setenv("GRAPHOS_VERIFIER_TOKEN", "verifier")
    paused = {"state": "RECONCILIATION_REQUIRED", "spent": 1000000}
    with patch("graphos.__main__.client", side_effect=lambda: api_client(
            lambda request: httpx.Response(200, json=paused))), \
         patch("graphos.worker.build_once") as build, patch("graphos.worker.verify_once") as verify:
        result = execute("example-run", "eve", 1000000)
    assert result["state"] == "RECONCILIATION_REQUIRED" and result["accepted"] is False
    assert "automatic retry blocked" in result["detail"]
    build.assert_not_called()
    verify.assert_not_called()


def test_execute_reports_new_cost_pause_before_verifier_or_retry(monkeypatch):
    monkeypatch.setenv("GRAPHOS_BUILDER_TOKEN", "builder")
    monkeypatch.setenv("GRAPHOS_VERIFIER_TOKEN", "verifier")
    states = iter([{"state": "RUNNING", "spent": 0, "tasks": [{"state": "PENDING"}],
                    "spec": {"max_attempts": 3}},
                   {"state": "RECONCILIATION_REQUIRED", "spent": 1000000}])
    with patch("graphos.__main__.client", side_effect=lambda: api_client(
            lambda request: httpx.Response(200, json=next(states)))), \
         patch("graphos.worker.build_once", return_value={"status": "failed"}) as build, \
         patch("graphos.worker.verify_once") as verify:
        result = execute("example-run", "eve", 1000000)
    assert result["state"] == "RECONCILIATION_REQUIRED" and result["accepted"] is False
    build.assert_called_once()
    verify.assert_not_called()


def test_cli_worker_error_is_sanitized_without_traceback(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["graphos", "execute", "example-run", "--builder", "eve"])
    with patch("graphos.__main__.execute", side_effect=WorkerError("private-token: secret-value")):
        with pytest.raises(SystemExit) as exited:
            main()
    assert exited.value.code == 1
    output = capsys.readouterr()
    assert "Worker request failed" in output.err
    assert "secret-value" not in output.err and "Traceback" not in output.err


@pytest.mark.parametrize("url", [
    "http://localhost:8000", "http://127.0.0.1:8000", "http://[::1]:8000",
    "https://api.example.com", "https://api.example.com:443/prefix", "HTTPS://EXAMPLE.COM",
])
def test_safe_api_urls_require_no_dns_or_network(url):
    with patch("socket.getaddrinfo", side_effect=AssertionError("validation must not resolve DNS")):
        assert validate_api_url(url) == url


@pytest.mark.parametrize("url", [
    "http://api.example.com", "http://localhost.attacker.test", "http://127.0.0.2",
    "http://127.1", "http://2130706433", "http://localhost.", "http://[::ffff:127.0.0.1]",
    "https://user:password@example.com", "https://@example.com", "http://localhost@evil.test",
    "https://example.com?secret=value", "https://example.com?", "https://example.com#fragment",
    "https://example.com#", "https://example.com:99999", "http://localhost:0",
    "https://example.com\\@localhost", "https://example.com\n", " https://example.com",
    "ftp://example.com", "http:///missing-host", "http://[invalid]", "", None,
])
def test_unsafe_api_urls_are_rejected_without_network(url):
    with patch("socket.getaddrinfo", side_effect=AssertionError("validation must not resolve DNS")):
        with pytest.raises(ValueError):
            validate_api_url(url)


def test_cli_rejects_remote_plaintext_before_creating_http_client(monkeypatch):
    monkeypatch.setenv("GRAPHOS_OPERATOR_TOKEN", "operator-secret")
    monkeypatch.setenv("GRAPHOS_API_URL", "http://api.example.com")
    with patch("graphos.__main__.httpx.Client") as http_client:
        with pytest.raises(ValueError, match="HTTPS"):
            client()
    http_client.assert_not_called()
