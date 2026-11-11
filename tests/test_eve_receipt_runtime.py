"""Real Eve + fake Gateway + real HTTP/Postgres; no paid calls or candidate execution."""
import json
import os
from pathlib import Path
import secrets
import subprocess
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import httpx
import psycopg
from psycopg import sql
import pytest

from graphos.artifacts import ArtifactStore
from graphos.ledger import Conflict, Ledger
from graphos.profiles import default_spec, fixture_files, get_profile
from graphos import worker
from scripts.acceptance import ManagedAPI, local_environment

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def runtime_api(tmp_path_factory):
    base = local_environment()
    dsn = base.get("GRAPHOS_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("PostgreSQL is required for real Eve receipt integration")
    assert (ROOT / "agents/eve/node_modules/eve").is_dir(), "npm ci in agents/eve is mandatory"
    schema = "test_eve_receipts_" + uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    parts = urlsplit(dsn)
    query = dict(parse_qsl(parts.query))
    query["options"] = f"-csearch_path={schema}"
    isolated = urlunsplit(parts._replace(query=urlencode(query)))
    env = {k: v for k, v in base.items() if not k.startswith(("GRAPHOS_", "AI_GATEWAY_", "VERCEL_"))}
    env.update(GRAPHOS_DATABASE_URL=isolated,
               GRAPHOS_ARTIFACT_ROOT=str(tmp_path_factory.mktemp("receipt-api-artifacts")),
               GRAPHOS_ALLOW_FIXTURE="1")
    if base.get("GRAPHOS_VERIFIER_IMAGE_DIGEST"):
        env["GRAPHOS_VERIFIER_IMAGE_DIGEST"] = base["GRAPHOS_VERIFIER_IMAGE_DIGEST"]
    for role in ("OPERATOR", "BUILDER", "VERIFIER"):
        env[f"GRAPHOS_{role}_TOKEN"] = secrets.token_urlsafe(48)
    api = ManagedAPI(env)
    try:
        built = subprocess.run(["npm", "run", "build:broker"], cwd=ROOT / "agents/eve",
                               env=env, capture_output=True, timeout=60)
        assert built.returncode == 0, "offline broker compilation failed"
        api.start()
        yield api, Ledger(isolated), isolated
    finally:
        api.close()
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.mark.parametrize("mode", ["happy", "interrupt", "kill-before-generation",
                                      "kill-after-generation", "kill-usage", "kill-terminal"])
def test_real_eve_callback_crash_boundaries(runtime_api, tmp_path, mode):
    api, ledger, dsn = runtime_api
    run = ledger.create_run(default_spec(), 2_000_000, uuid4().hex)
    claim = ledger.claim_build(run["id"], "builder:offline-runtime", 1_000_000, 600)
    with httpx.Client(base_url=api.url, trust_env=False, timeout=5) as client:
        granted = client.post(f"/v1/runs/{run['id']}/tasks/{claim['task_id']}/receipt-grant",
            headers={"Authorization": "Bearer " + api.env["GRAPHOS_BUILDER_TOKEN"]},
            json={key: claim[key] for key in ("token", "epoch", "revision", "input_hash")})
        assert granted.status_code == 200
        grant = {key: granted.json()[key] for key in ("run_id", "attempt_id", "capture_token")}
        envelope = tmp_path / "private-envelope.json"
        envelope.write_text(json.dumps({"receipt": grant,
            "request": {"claim": claim, "profile": get_profile("static-web"), "dependencies": []}}))
        envelope.chmod(0o600)
        env = {key: os.environ[key] for key in ("PATH", "HOME", "NODE_EXTRA_CA_CERTS") if key in os.environ}
        env.update(GRAPHOS_RECEIPT_SMOKE_ENVELOPE_FILE=str(envelope),
                   GRAPHOS_RECEIPT_SMOKE_API_URL=api.url,
                   GRAPHOS_RECEIPT_SMOKE_ALLOW_FAKE_RECEIPTS="1", GRAPHOS_RECEIPT_SMOKE_MODE=mode)
        result = subprocess.run(["node", "test/receipt-runtime-smoke.mjs"], cwd=ROOT / "agents/eve",
                                env=env, capture_output=True, text=True, timeout=150)
        assert result.returncode == 0, result.stderr[-3000:]
        report = json.loads(result.stdout.strip().splitlines()[-1])
        assert report["fixture_model_calls"] == 1 and report["live_model_calls"] == 0
        assert report["settles_cost"] is False
        api.restart()
        path = f"/v1/runs/{run['id']}/attempts/{claim['attempt_id']}/receipts"
        response = client.get(path, headers={"Authorization": "Bearer " + api.env["GRAPHOS_OPERATOR_TOKEN"]})
        assert response.status_code == 200
        receipts = response.json()
        assert receipts["settles_cost"] is False
        assert len(receipts["models"]) == 1
        model = receipts["models"][0]
        assert model["generation_id"] == "gen_fixture_" + claim["attempt_id"]
        assert (model["usage"] is not None) == (mode in {"happy", "kill-usage", "kill-terminal"})
        assert grant["capture_token"] not in response.text
        before = ledger.get_run(run["id"])
        assert (before["spent"], before["reserved"], before["state"]) == (0, 1_000_000, "ACTIVE")
        # Fence this synthetic attempt, then repeat its already captured facts.
        # A new intent must fail while late historical callbacks still ACK.
        with psycopg.connect(dsn) as conn:
            conn.execute("UPDATE graphos_attempts SET expires_at=clock_timestamp()-interval '1 second' WHERE id=%s",
                         (claim["attempt_id"],))
        cap = {"Authorization": "Bearer " + grant["capture_token"]}
        for item in reversed(receipts["events"]):
            duplicate = client.post(path, headers=cap, json=item["payload"])
            assert duplicate.status_code == 200 and duplicate.json()["duplicate"] is True
        intent = {"kind": "model_started", "event_id": "model_started:stale",
                  "session_id": receipts["capture"]["session_id"], "model_run_id": "stale",
                  "model_id": model["model_id"], "model_attempt": 0}
        assert client.post(path, headers=cap, json=intent).status_code == 409
        after = ledger.get_run(run["id"])
        assert {k: before[k] for k in ("spent", "reserved", "state")} == {
            k: after[k] for k in ("spent", "reserved", "state")}
        assert after["tasks"] == before["tasks"]
        # Report only synthetic public facts, not capabilities or envelope paths.
        report.update(api_restart_preserved_receipts=True, late_duplicates_idempotent=True,
                      stale_intent_rejected=True, accounting_unchanged=True)
        output = ROOT / ".state/receipt-runtime-tests"
        output.mkdir(parents=True, exist_ok=True)
        (output / f"runtime-{mode}.json").write_text(json.dumps(report, indent=2) + "\n")


@pytest.mark.parametrize("changed", [False, True])
def test_noop_repair_through_real_worker_api_and_ledger(runtime_api, monkeypatch, changed):
    api, ledger, _ = runtime_api
    run = ledger.create_run(default_spec(), 2_000_000, uuid4().hex)
    files = fixture_files("static-web")
    digest = ArtifactStore(Path(api.env["GRAPHOS_ARTIFACT_ROOT"])).put_bundle(files)
    first = ledger.claim_build(run["id"], "builder:seed", 100)
    ledger.submit_build(**{k: first[k] for k in ("run_id", "task_id", "token", "epoch", "revision", "input_hash")},
                        candidate_hash=digest, actual_cost=0, provenance={"mode": "fixture"})
    verifier = ledger.claim_verify(run["id"], "verifier:seed")
    evidence = "b" * 64
    ledger.submit_verification(**{k: verifier[k] for k in ("run_id", "task_id", "token", "epoch", "revision", "input_hash",
                                                         "candidate_hash", "suite_hash", "policy_hash")},
        passed=False, evidence_hash=evidence,
        report={"passed": False, "checks": [{"name": "visible_focus", "passed": False,
                                             "detail": "synthetic diagnostic for binding test"}]})

    def fake_adapter(claim, profile, dependencies, repair, *, receipt):
        assert repair["candidate_hash"] == digest and repair["evidence_hash"] == evidence
        assert repair["verifier_attempt_id"] == verifier["attempt_id"] and repair["files"] == files
        model_run, session = "run_" + uuid4().hex, "session_" + uuid4().hex
        generation = "gen_noop_" + uuid4().hex
        counts = {"input_tokens": 20, "output_tokens": 8, "cache_read_tokens": 0,
                  "cache_write_tokens": 0, "actual_cost_microdollars": 17}
        events = [{"kind": "session", "event_id": "session", "session_id": session,
                   **{k: claim[k] for k in ("task_id", "epoch", "revision", "input_hash")}}]
        model = {"session_id": session, "model_run_id": model_run,
                 "model_id": "openai/gpt-5.1-codex-mini", "model_attempt": 0}
        events += [{"kind": "model_started", "event_id": "model_started:" + model_run, **model},
                   {"kind": "usage", "event_id": "usage:" + model_run, **model,
                    "usage": {**counts, "generation_id": generation, "finish_reason": "tool-calls"}}]
        with httpx.Client(base_url=api.url, trust_env=False) as client:
            for event in events:
                response = client.post(f"/v1/runs/{run['id']}/attempts/{claim['attempt_id']}/receipts",
                    headers={"Authorization": "Bearer " + receipt["capture_token"]}, json=event)
                assert response.status_code == 200
        output = dict(files)
        if changed:
            output["styles.css"] += "\ninput:focus-visible{outline:3px solid #134fbe}\n"
        return {"files": output, "usage": {**counts, "model_runs": 1,
            "cost_source": "eve_gateway_usage_events", "generations": [{"run_id": model_run,
                "generation_id": generation, "finish_reason": "tool-calls"}]}, "provenance": {"mode": "eve"}}

    monkeypatch.setattr(worker, "_eve_environment", lambda: {})
    monkeypatch.setattr(worker, "_eve_build", fake_adapter)
    result = worker.build_once(api.url, api.env["GRAPHOS_BUILDER_TOKEN"], run["id"], builder="eve", reserve=100)
    assert result["status"] == ("submitted" if changed else "failed")
    state = ledger.get_run(run["id"])
    assert (state["spent"], state["reserved"]) == (17, 0)
    # Starting the repair clears the task's active evidence slot. The rejected
    # attempt remains immutable history, never reusable acceptance evidence.
    assert state["tasks"][0]["evidence_hash"] is None
    assert state["tasks"][0]["verification"] is None
    with psycopg.connect(runtime_api[2]) as conn:
        retained = conn.execute("SELECT result FROM graphos_attempts WHERE id=%s",
                                (verifier["attempt_id"],)).fetchone()[0]
    assert retained["evidence_hash"] == evidence and retained["passed"] is False
    with pytest.raises(Conflict):
        ledger.release_manifest(run["id"])
    if changed:
        fresh = ledger.claim_verify(run["id"], "verifier:fresh")
        assert fresh["candidate_hash"] != digest
    else:
        assert ledger.claim_verify(run["id"], "verifier:redundant") is None
        assert len([event for event in state["events"] if event["kind"] == "BUILD_SUBMITTED"]) == 1
        failed = [event for event in state["events"] if event["kind"] == "BUILD_FAILED"]
        assert failed[0]["payload"]["usage"]["actual_cost_microdollars"] == 17
