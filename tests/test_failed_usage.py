"""Known failure accounting preserves receipt IDs without disclosing raw output."""
import copy
import json
from unittest.mock import patch

import pytest

from graphos.profiles import get_profile
from graphos.worker import BuildFailure, _eve_build, _safe_failure_usage, build_once


def usage():
    return {"input_tokens": 20, "output_tokens": 8, "cache_read_tokens": 0,
            "cache_write_tokens": 0, "actual_cost_microdollars": 17, "model_runs": 1,
            "cost_source": "eve_gateway_usage_events", "generations": [
                {"run_id": "run_0", "generation_id": "gen_receipt123", "finish_reason": "stop"}]}


def claim():
    profile = get_profile("static-web")
    return {"run_id": "run", "attempt_id": "attempt-1", "task_id": "task", "token": "private-lease", "epoch": 1, "revision": 1,
            "input_hash": "a" * 64, "profile": profile["id"], "reservation": 100,
            "requirements": profile["acceptance_criteria"], "suite_hash": profile["suite_hash"],
            "policy_hash": profile["policy_hash"]}


def receipt():
    return {"run_id": "run", "attempt_id": "attempt-1", "capture_token": "c" * 64}


def test_failure_receipts_are_allowlisted_and_bound_to_known_cost():
    raw = usage()
    raw["private_provider_error"] = "secret"
    raw["generations"][0]["authorization"] = "secret"
    assert _safe_failure_usage(raw, 17) == usage()
    assert _safe_failure_usage(raw, None) is None
    assert _safe_failure_usage(raw, 18) is None
    assert "secret" not in json.dumps(_safe_failure_usage(raw, 17))


@pytest.mark.parametrize("change", [
    lambda u: u.update(model_runs=4),
    lambda u: u.update(input_tokens=True),
    lambda u: u.update(output_tokens=-1),
    lambda u: u.update(cost_source="model_self_report"),
    lambda u: u.update(generations=[]),
    lambda u: u["generations"][0].update(finish_reason={"private": "message"}),
    lambda u: u["generations"][0].update(generation_id="https://private.example/token"),
    lambda u: u["generations"][0].update(run_id=[]),
    lambda u: u.update(model_runs=2, generations=[u["generations"][0]] * 2),
])
def test_malformed_failure_metadata_is_not_forwarded(change):
    raw = copy.deepcopy(usage())
    change(raw)
    assert _safe_failure_usage(raw, 17) is None


def test_known_adapter_failure_keeps_receipts_and_never_returns_artifact():
    error = {"error": "eve_turn_not_completed", "cost_known": True,
             "actual_cost_microdollars": 17, "usage": usage(), "private": "hidden"}
    with patch("graphos.worker._eve_environment", return_value={}), \
         patch("graphos.worker.run_bounded", return_value=(1, b"", json.dumps(error).encode())):
        with pytest.raises(BuildFailure) as caught:
            _eve_build(claim(), get_profile("static-web"), [], receipt=receipt())
    assert caught.value.actual_cost == 17 and caught.value.usage == usage()
    assert "hidden" not in str(caught.value)


def test_worker_reports_settled_failure_usage_without_submitting_candidate():
    calls = []
    def api(url, token, path, data=None):
        calls.append((path, data))
        if path.endswith("/receipt-grant"):
            return receipt()
        return claim() if path.endswith("claim/build") else {"state": "EXHAUSTED"}
    with patch("graphos.worker._request", side_effect=api), \
         patch("graphos.worker._eve_environment", return_value={}), \
         patch("graphos.worker._eve_build", side_effect=BuildFailure("schema rejected", 17, usage())):
        result = build_once("http://localhost:8000", "test-bearer", "run", "eve", reserve=100)
    assert result["status"] == "failed" and result["usage"] == usage()
    assert calls[-1][0].endswith("/fail") and calls[-1][1]["cost_known"] is True
    assert calls[-1][1]["actual_cost"] == 17
    assert calls[-1][1]["usage"] == usage()
    assert all(not path.endswith("/submit") for path, _ in calls)


def test_invalid_receipt_metadata_is_discarded_without_losing_known_scalar_cost():
    raw = usage()
    raw["generations"][0]["generation_id"] = "https://private.example/hidden"
    raw["provider_response"] = "private response text"
    error = {"error": "eve_turn_not_completed", "cost_known": True,
             "actual_cost_microdollars": 17, "usage": raw}
    calls = []
    def api(url, token, path, data=None):
        calls.append((path, data))
        if path.endswith("/receipt-grant"):
            return receipt()
        return claim() if path.endswith("claim/build") else {"state": "EXHAUSTED"}
    with patch("graphos.worker._request", side_effect=api), \
         patch("graphos.worker._eve_environment", return_value={}), \
         patch("graphos.worker.run_bounded", return_value=(1, b"", json.dumps(error).encode())):
        result = build_once("http://localhost:8000", "test-bearer", "run", "eve", reserve=100)
    assert result["status"] == "failed" and "usage" not in result
    failure = calls[-1][1]
    assert calls[-1][0].endswith("/fail")
    assert failure["actual_cost"] == 17 and failure["cost_known"] is True
    assert failure.get("usage") is None
    assert "private.example" not in json.dumps(failure) and "private response" not in json.dumps(failure)
    assert all(not path.endswith("/submit") for path, _ in calls)
