"""An identical rejected candidate consumes generation cost, not verifier work."""
from unittest.mock import patch

import pytest

from graphos.artifacts import bundle_digest
from graphos.profiles import fixture_files, get_profile
from graphos.worker import build_once


@pytest.mark.parametrize("changed", [False, True])
def test_repair_identity_controls_submission_without_discarding_cost(changed):
    profile = get_profile("static-web")
    files = fixture_files("static-web")
    digest = bundle_digest(files)
    claim = {"run_id": "run", "attempt_id": "attempt", "task_id": "task", "token": "lease",
             "epoch": 3, "revision": 1, "input_hash": "a" * 64,
             "profile": "static-web", "reservation": 100,
             "requirements": profile["acceptance_criteria"],
             "suite_hash": profile["suite_hash"], "policy_hash": profile["policy_hash"]}
    claim["repair"] = {key: claim[key] for key in ("revision", "input_hash", "suite_hash", "policy_hash")}
    claim["repair"].update(candidate_hash=digest, evidence_hash="b" * 64,
                           verifier_attempt_id="verifier", checks=[{"name": "visible_focus", "passed": False}],
                           truncated=False)
    candidate = dict(files)
    if changed:
        candidate["styles.css"] += "\ninput[type=checkbox]:focus-visible {outline:3px solid #134fbe;}\n"
    usage = {"input_tokens": 20, "output_tokens": 8, "cache_read_tokens": 0,
             "cache_write_tokens": 0, "actual_cost_microdollars": 17, "model_runs": 1,
             "cost_source": "eve_gateway_usage_events", "generations": [
                 {"run_id": "run_0", "generation_id": "gen_noop_receipt", "finish_reason": "tool-calls"}]}
    calls = []

    def api(url, token, path, data=None, **kwargs):
        calls.append((path, data))
        if path.endswith("claim/build"):
            return claim
        if path.startswith("/artifacts/"):
            return {"files": files, "manifest_hash": digest}
        if path.endswith("receipt-grant"):
            return {"run_id": "run", "attempt_id": "attempt", "capture_token": "x" * 64}
        return {"state": "ACTIVE"}

    with patch("graphos.worker._request", side_effect=api), \
         patch("graphos.worker._eve_environment", return_value={}), \
         patch("graphos.worker._eve_build", return_value={"files": candidate, "usage": usage,
                                                          "provenance": {"mode": "eve"}}):
        result = build_once("http://localhost:8000", "builder-token", "run", "eve", reserve=100)
    if changed:
        assert result["status"] == "submitted"
        assert calls[-1][0].endswith("/submit")
        assert calls[-1][1]["files"] == candidate
    else:
        assert result["status"] == "failed"
        assert result["usage"] == usage
        assert "unchanged rejected candidate" in result["reason"]
        assert calls[-1][0].endswith("/fail")
        assert calls[-1][1]["cost_known"] is True
        assert all(not path.endswith("/submit") for path, _ in calls)
    assert calls[-1][1]["actual_cost"] == 17
