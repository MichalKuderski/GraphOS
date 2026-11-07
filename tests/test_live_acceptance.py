from contextlib import contextmanager
from unittest.mock import Mock
import io

import pytest

from scripts import live_acceptance as live


def test_explicit_dispatch_and_budget_gate_precedes_services(monkeypatch):
    service = Mock()
    monkeypatch.setattr(live, "LiveEve", service)
    for argv in ([], ["--execute", "--budget", "5000001"], ["--execute", "--max-attempts", "3"]):
        with pytest.raises(SystemExit) as exc:
            live.main(argv)
        assert exc.value.code == 2
    service.assert_not_called()


def test_only_model_server_receives_key_and_no_role_credentials():
    env = {"PATH": "/bin", "AI_GATEWAY_API_KEY": "secret", "GRAPHOS_EVE_TOKEN": "e" * 32,
           "GRAPHOS_OPERATOR_TOKEN": "o" * 32, "GRAPHOS_DATABASE_URL": "database",
           "VERCEL_TOKEN": "vercel-secret", "AWS_SECRET_ACCESS_KEY": "aws-secret",
           "HTTPS_PROXY": "https://proxy", "NODE_EXTRA_CA_CERTS": "/ca.pem"}
    model_env = live.eve_environment(env)
    assert model_env["AI_GATEWAY_API_KEY"] == "secret"
    assert model_env["GRAPHOS_GATEWAY_BUDGET_USD"] == "1"
    assert model_env["NODE_USE_ENV_PROXY"] == "1"
    assert not {"GRAPHOS_OPERATOR_TOKEN", "GRAPHOS_DATABASE_URL", "VERCEL_TOKEN",
                "AWS_SECRET_ACCESS_KEY"}.intersection(model_env)
    assert "AI_GATEWAY_API_KEY" not in live.control_environment(env)
    assert "VERCEL_TOKEN" not in live.control_environment(env)


def test_build_has_no_live_credentials_and_failure_aborts(monkeypatch):
    service = object.__new__(live.LiveEve)
    service.env = {"PATH": "/bin", "AI_GATEWAY_API_KEY": "secret",
                   "GRAPHOS_EVE_TOKEN": "broker", "GRAPHOS_LIVE_ENABLED": "1"}
    service.log = io.BytesIO()
    build = Mock(return_value=Mock(returncode=1))
    monkeypatch.setattr(live.subprocess, "run", build)
    with pytest.raises(RuntimeError, match="eve_build_failed"):
        service.build()
    assert build.call_args.args[0] == ["npm", "run", "build"]
    assert not any(k.startswith(("AI_GATEWAY_", "GRAPHOS_", "VERCEL_"))
                   for k in build.call_args.kwargs["env"])


def test_source_change_during_build_prevents_live_service_start(monkeypatch, tmp_path):
    eve, controller = Mock(), Mock()
    monkeypatch.setattr(live, "LiveEve", Mock(return_value=eve))
    monkeypatch.setattr(live, "ManagedAPI", Mock(return_value=controller))
    monkeypatch.setattr(live, "local_environment", lambda: {})
    monkeypatch.setattr(live, "source_digest", Mock(side_effect=["old", "new", "new"]))
    assert live.main(["--execute", "--output", str(tmp_path / "result.json")]) == 1
    eve.build.assert_called_once()
    eve.start.assert_not_called()
    controller.start.assert_not_called()
    eve.close.assert_called_once()


def setup_run(monkeypatch, builds, verifications, states):
    build = Mock(side_effect=builds)
    verify = Mock(side_effect=verifications)
    monkeypatch.setattr(live, "build_once", build)
    monkeypatch.setattr(live, "verify_once", verify)
    responses = iter(states)

    @contextmanager
    def client():
        yield Mock(get=lambda path: next(responses))

    monkeypatch.setattr(live, "client", client)
    monkeypatch.setattr(live, "checked", lambda response: response)
    return build, verify


def state(name="ACTIVE", spent=10):
    return {"state": name, "spent": spent}


def run(report, maximum=2):
    return live.run_attempts("run", {"GRAPHOS_API_URL": "http://127.0.0.1:8000",
                             "GRAPHOS_BUILDER_TOKEN": "builder", "GRAPHOS_VERIFIER_TOKEN": "verifier"},
                             maximum, report, lambda: None)


def test_uncertain_build_is_retained_and_never_retried_or_verified(monkeypatch):
    build, verify = setup_run(monkeypatch, [{"status": "failed", "claim": {"token": "secret"}}], [],
                              [state("RECONCILIATION_REQUIRED", 1000000)])
    report = {"attempts": []}
    assert not run(report)
    assert build.call_count == 1
    verify.assert_not_called()
    assert report["spent_microdollars"] == 1000000
    assert report["attempts"][0]["stage"] == "STOPPED_AFTER_BUILD"
    assert "secret" not in str(report)


def test_verified_failure_is_retained_when_bounded_repair_succeeds(monkeypatch):
    build, verify = setup_run(monkeypatch,
        [{"status": "submitted", "provenance": {"mode": "eve", "secret": "never-copy"}}] * 2,
        [{"status": "verified", "passed": False, "report": {"passed": False}},
         {"status": "verified", "passed": True, "report": {"passed": True}}],
        [state(), state(), state(), state("READY_FOR_RELEASE", 20)])
    report = {"attempts": []}
    assert run(report)
    assert build.call_count == verify.call_count == 2
    assert [a["passed"] for a in report["attempts"]] == [False, True]
    assert "never-copy" not in str(report)


def test_failed_verification_at_limit_never_starts_extra_build(monkeypatch):
    build, verify = setup_run(monkeypatch, [{"status": "submitted"}],
        [{"status": "verified", "passed": False}], [state(), state("EXHAUSTED")])
    assert not run({"attempts": []}, maximum=1)
    assert build.call_count == verify.call_count == 1
