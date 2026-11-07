import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from graphos.artifacts import (ArtifactError, ArtifactStore, MAX_FILE_BYTES,
                               bundle_digest, canonical, materialize_files, validate_files)
from graphos.profiles import default_spec, fixture_files, get_profile, require_active, ProfileError
from graphos.sandbox import docker_command, ProcessError, run_bounded, verify_bundle
from graphos.worker import build_once, verify_once, WorkerError, BuildFailure, _eve_environment, _eve_build, _request


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = ArtifactStore(self.root / "store")

    def tearDown(self):
        self.temp.cleanup()

    def test_bundle_roundtrip_and_order_independent_identity(self):
        files = {"app.js": "const x = 1;", "index.html": "<main>✓</main>"}
        digest = self.store.put_bundle(files)
        self.assertEqual(digest, self.store.put_bundle(dict(reversed(list(files.items())))))
        self.assertEqual(digest, bundle_digest(files))
        self.assertEqual(self.store.get_bundle(digest), files)

    def test_unsafe_paths_are_rejected(self):
        for name in ("../secret", "/absolute", "a/../../b", "a//b", "a/./b", "a\\b",
                     "a\x00b", ".git/config", ".env", ".env.local", "CON.txt", "a/PRN",
                     "a/last.", "file\n.js"):
            with self.subTest(path=name), self.assertRaises(ArtifactError):
                self.store.put_bundle({name: "value"})

    def test_case_and_directory_collisions_are_rejected(self):
        for files in ({"App.js": "", "app.js": ""}, {"a": "", "a/b": ""},
                      {"A": "", "a/b": ""}):
            with self.assertRaises(ArtifactError):
                validate_files(files)

    def test_binary_and_oversized_files_are_rejected(self):
        for files in ({"a": b"binary"}, {"a": "x" * (MAX_FILE_BYTES + 1)},
                      {"a": "\ud800"}, {}):
            with self.assertRaises(ArtifactError):
                self.store.put_bundle(files)

    def test_content_tampering_is_detected(self):
        digest = self.store.put_bundle({"app.js": "good"})
        blob = self.store.objects / hashlib.sha256(b"good").hexdigest()
        blob.chmod(0o600)
        blob.write_text("evil")
        with self.assertRaises(ArtifactError):
            self.store.get_bundle(digest)

    def test_symlink_object_and_directory_are_rejected(self):
        digest = self.store.put_json({"evidence": True})
        blob = self.store.objects / digest
        copy = self.root / "outside"
        copy.write_bytes(blob.read_bytes())
        blob.unlink()
        blob.symlink_to(copy)
        with self.assertRaises(ArtifactError):
            self.store.get_json(digest)
        symlink = self.root / "linked"
        symlink.symlink_to(self.store.root, target_is_directory=True)
        with self.assertRaises(ArtifactError):
            ArtifactStore(symlink)

    def test_fifo_object_is_rejected_without_blocking(self):
        digest = "f" * 64
        os.mkfifo(self.store.objects / digest)
        with self.assertRaises(ArtifactError):
            self.store.get_json(digest)

    def test_invalid_digest_cannot_read_outside_store(self):
        for digest in ("../secret", "f" * 63, "F" * 64, "f" * 64 + "/x"):
            with self.assertRaises(ArtifactError):
                self.store.get_bundle(digest)

    def test_manifest_size_lie_is_rejected(self):
        digest = self.store.put_bundle({"a": "hello"})
        manifest = json.loads((self.store.objects / digest).read_bytes())
        manifest["files"][0]["size"] = 0
        encoded = canonical(manifest)
        bad_digest = hashlib.sha256(encoded).hexdigest()
        (self.store.objects / bad_digest).write_bytes(encoded)
        with self.assertRaises(ArtifactError):
            self.store.get_bundle(bad_digest)

    def test_evidence_and_bundle_types_cannot_be_confused(self):
        digest = self.store.put_json({"passed": False, "checks": []})
        self.assertFalse(self.store.get_json(digest)["passed"])
        with self.assertRaises(ArtifactError):
            self.store.get_bundle(digest)

    def test_materialization_rejects_nonempty_or_symlink_destination(self):
        destination = self.root / "candidate"
        materialize_files({"nested/a.js": "safe"}, destination)
        self.assertEqual((destination / "nested/a.js").read_text(), "safe")
        self.assertEqual(destination.stat().st_mode & 0o777, 0o755)
        self.assertEqual((destination / "nested").stat().st_mode & 0o777, 0o755)
        self.assertEqual((destination / "nested/a.js").stat().st_mode & 0o777, 0o444)
        with self.assertRaises(ArtifactError):
            materialize_files({"other.js": ""}, destination)
        linked = self.root / "link"
        linked.symlink_to(destination, target_is_directory=True)
        with self.assertRaises(ArtifactError):
            materialize_files({"other.js": ""}, linked)


class SandboxTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict(os.environ, {"GRAPHOS_VERIFIER_IMAGE_DIGEST": "sha256:" + "a" * 64})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_policy_command_is_constrained_and_proxy_values_are_cleared(self):
        command = docker_command("sha256:" + "a" * 64, Path("/tmp/candidate"),
                                 Path("/tmp/trusted.py"), "graphos-test",
                                 docker_config=Path("/tmp/empty-docker-config"))
        for flag in ("--read-only", "--network", "--cap-drop", "--pids-limit", "--memory",
                     "--memory-swap", "--cpus", "--user", "--security-opt"):
            self.assertIn(flag, command)
        self.assertIn("unix:///var/run/docker.sock", command)
        self.assertIn("no-new-privileges", command)
        self.assertIn("HTTP_PROXY=", command)
        self.assertEqual(command[command.index("--network") + 1], "none")
        mounts = [command[i + 1] for i, value in enumerate(command) if value == "--mount"]
        self.assertTrue(all(value.endswith(",readonly") for value in mounts))
        self.assertFalse(any("docker.sock" in mount for mount in mounts))

    def test_docker_unavailable_fails_closed(self):
        with patch("graphos.sandbox.shutil.which", return_value=None), patch("graphos.sandbox.run_bounded") as runner:
            report = verify_bundle(fixture_files(), get_profile("static-web")["acceptance_criteria"])
        self.assertFalse(report["passed"])
        runner.assert_not_called()

    def test_noncanonical_requirements_are_not_certified(self):
        with patch("graphos.sandbox.run_bounded") as runner:
            report = verify_bundle(fixture_files(), ["Build a trading platform"])
        self.assertFalse(report["passed"])
        runner.assert_not_called()

    def test_self_reported_pass_without_complete_checks_is_rejected(self):
        responses = [(0, ("sha256:" + "a" * 64).encode(), b""),
                     (0, b'{"passed":true,"checks":[]}', b""), (0, b"", b"")]
        with patch("graphos.sandbox.shutil.which", return_value="docker"), \
             patch("graphos.sandbox.run_bounded", side_effect=responses):
            report = verify_bundle(fixture_files(), get_profile("static-web")["acceptance_criteria"])
        self.assertFalse(report["passed"])

    def test_container_timeout_triggers_force_cleanup(self):
        calls = []
        def fake(command, **kwargs):
            calls.append((command, kwargs))
            if "inspect" in command:
                return 0, ("sha256:" + "a" * 64).encode(), b""
            if "run" in command:
                raise ProcessError("deadline")
            return 0, b"", b""
        with patch("graphos.sandbox.shutil.which", return_value="docker"), \
             patch("graphos.sandbox.run_bounded", side_effect=fake), \
             patch.dict(os.environ, {"DOCKER_HOST": "tcp://hostile:2375", "HTTPS_PROXY": "secret"}):
            report = verify_bundle(fixture_files(), get_profile("static-web")["acceptance_criteria"])
        self.assertFalse(report["passed"])
        self.assertIn("--force", calls[-1][0])
        self.assertTrue(all("DOCKER_HOST" not in kwargs["env"] and "HTTPS_PROXY" not in kwargs["env"]
                            for _, kwargs in calls))

    def test_changed_image_is_rejected_before_container_execution(self):
        with patch("graphos.sandbox.shutil.which", return_value="docker"), \
             patch("graphos.sandbox.run_bounded", side_effect=[(0, ("sha256:" + "b" * 64).encode(), b""),
                                                                (0, b"", b"")]) as runner:
            report = verify_bundle(fixture_files(), get_profile("static-web")["acceptance_criteria"])
        self.assertFalse(report["passed"])
        self.assertEqual(report["checks"][0]["name"], "sandbox_image_pin")
        self.assertFalse(any("run" in call.args[0] for call in runner.call_args_list))

    def test_subprocess_output_cap_and_timeout(self):
        with self.assertRaises(ProcessError):
            run_bounded([sys.executable, "-c", "print('x'*10000)"], timeout=3, output_limit=100)
        with self.assertRaises(ProcessError):
            run_bounded([sys.executable, "-c", "import time;time.sleep(3)"], timeout=.05, output_limit=100)

    def test_exited_parent_cannot_leave_child_running_after_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            pid_file = Path(directory) / "child.pid"
            program = ("import subprocess,sys,pathlib; "
                       "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']); "
                       f"pathlib.Path({str(pid_file)!r}).write_text(str(p.pid))")
            with self.assertRaises(ProcessError):
                run_bounded([sys.executable, "-c", program], timeout=.3, output_limit=100)
            pid = int(pid_file.read_text())
            terminated = False
            for _ in range(50):
                try:
                    state = Path(f"/proc/{pid}/stat").read_text().split()[2]
                    terminated = state == "Z"
                except FileNotFoundError:
                    terminated = True
                if terminated:
                    break
                time.sleep(.01)
            self.assertTrue(terminated, "child survived its process-group deadline")


class WorkerTests(unittest.TestCase):
    def claim(self, **changes):
        profile = get_profile("static-web")
        return {"task_id": "task-1", "task_key": "app", "token": "lease-secret", "epoch": 1,
                "revision": 1, "input_hash": "a" * 64, "profile": "static-web",
                "suite_hash": profile["suite_hash"], "policy_hash": profile["policy_hash"],
                "requirements": profile["acceptance_criteria"], "dependencies": {},
                "reservation": 1, **changes}

    def test_fixture_is_explicitly_labeled_and_not_ai(self):
        calls = []
        def api(url, token, path, data=None, **kwargs):
            calls.append((path, data))
            return self.claim() if path.endswith("claim/build") else {"state": "SUBMITTED"}
        with patch("graphos.worker._request", side_effect=api), patch("graphos.worker._eve_build") as live:
            result = build_once("http://127.0.0.1:8000", "builder-secret", "run")
        self.assertEqual(result["status"], "submitted")
        self.assertEqual(result["provenance"]["mode"], "fixture")
        self.assertFalse(result["provenance"]["ai_generated"])
        self.assertEqual(calls[-1][1]["actual_cost"], 0)
        live.assert_not_called()

    def test_missing_eve_auth_never_claims_or_uses_fixture(self):
        with patch.dict(os.environ, {}, clear=True), patch("graphos.worker._request") as api, \
             patch("graphos.worker.fixture_files") as fixture:
            with self.assertRaises(WorkerError):
                build_once("http://localhost:8000", "secret", "run", "eve")
        api.assert_not_called()
        fixture.assert_not_called()

    def test_remote_plaintext_never_sends_worker_credentials(self):
        with patch("urllib.request.build_opener") as opener:
            with self.assertRaises(WorkerError):
                _request("http://remote.example", "private-bearer", "/runs/test/claim/build", {})
        opener.assert_not_called()

    def test_control_plane_transport_disables_ambient_proxy(self):
        with patch.dict(os.environ, {"HTTP_PROXY": "http://untrusted-proxy.invalid", "NO_PROXY": ""}), \
             patch("urllib.request.build_opener") as opener:
            opener.return_value.open.return_value.__enter__.return_value.read.return_value = b"{}"
            self.assertEqual(_request("http://localhost:8000", "private-bearer", "/runs"), {})
        self.assertEqual(opener.call_args.args[0].proxies, {})

    def test_adapter_environment_excludes_broker_and_model_secrets(self):
        with patch.dict(os.environ, {"GRAPHOS_EVE_TOKEN": "eve-secret", "GRAPHOS_BUILDER_TOKEN": "broker-secret",
                                      "GRAPHOS_DATABASE_URL": "db-secret", "AI_GATEWAY_API_KEY": "provider-secret"}):
            environment = _eve_environment()
        self.assertEqual(environment["GRAPHOS_EVE_TOKEN"], "eve-secret")
        self.assertNotIn("GRAPHOS_BUILDER_TOKEN", environment)
        self.assertNotIn("GRAPHOS_DATABASE_URL", environment)
        self.assertNotIn("AI_GATEWAY_API_KEY", environment)

    def test_dependencies_map_is_resolved_by_hash_before_live_build(self):
        files = fixture_files()
        digest = bundle_digest(files)
        claim = self.claim(dependencies={"dependency-task": digest})
        output = {"files": files, "usage": {"actual_cost_microdollars": 0}, "provenance": {"mode": "eve"}}
        def api(url, token, path, data=None, **kwargs):
            if path.endswith("claim/build"):
                return claim
            if path == "/artifacts/" + digest:
                self.assertEqual(kwargs["lease_headers"]["X-GraphOS-Lease-Token"], claim["token"])
                return {"manifest_hash": digest, "files": files}
            return {"state": "SUBMITTED"}
        with patch("graphos.worker._request", side_effect=api), \
             patch("graphos.worker._eve_environment", return_value={}), \
             patch("graphos.worker._eve_build", return_value=output) as live:
            result = build_once("http://localhost:8000", "secret", "run", "eve", reserve=1)
        self.assertEqual(result["status"], "submitted")
        self.assertEqual(live.call_args.args[2], [{"candidate_hash": digest, "files": files}])

    def test_verifier_rejects_wrong_bundle_despite_correct_returned_hash(self):
        good = fixture_files()
        digest = bundle_digest(good)
        bad = {**good, "app.js": ""}
        claim = self.claim(candidate_hash=digest)
        with patch("graphos.worker._request", side_effect=[claim, {"manifest_hash": digest, "files": bad}]), \
             patch("graphos.worker.verify_bundle") as verifier:
            with self.assertRaises(WorkerError):
                verify_once("http://localhost:8000", "secret", "run")
        verifier.assert_not_called()

    def test_repair_resolves_rejected_candidate_with_current_lease_and_passes_feedback(self):
        files = fixture_files()
        digest = bundle_digest(files)
        claim = self.claim()
        feedback = {key: claim[key] for key in ("revision", "input_hash", "suite_hash", "policy_hash")}
        feedback.update(candidate_hash=digest, evidence_hash="e" * 64,
                        verifier_attempt_id="prior-verifier", truncated=False,
                        checks=[{"name": "add_task", "passed": False, "detail": "Missing task"}])
        claim["repair"] = feedback
        output = {"files": files, "usage": {"actual_cost_microdollars": 0}, "provenance": {"mode": "eve"}}
        def api(url, token, path, data=None, **kwargs):
            if path.endswith("claim/build"):
                return claim
            if path == "/artifacts/" + digest:
                self.assertEqual(kwargs["lease_headers"]["X-GraphOS-Lease-Token"], claim["token"])
                return {"manifest_hash": digest, "files": files}
            return {"state": "SUBMITTED"}
        with patch("graphos.worker._request", side_effect=api), \
             patch("graphos.worker._eve_environment", return_value={}), \
             patch("graphos.worker._eve_build", return_value=output) as live:
            result = build_once("http://localhost:8000", "secret", "run", "eve", reserve=1)
        self.assertEqual(result["status"], "submitted")
        self.assertEqual(live.call_args.args[3], {**feedback, "files": files})
        self.assertNotIn("files", claim["repair"])

    def test_invalid_repair_is_rejected_before_model_work_and_charged_zero(self):
        files = fixture_files()
        digest = bundle_digest(files)
        for defect in ("stale", "tampered"):
            with self.subTest(defect=defect):
                claim = self.claim(reservation=100)
                feedback = {key: claim[key] for key in ("revision", "input_hash", "suite_hash", "policy_hash")}
                feedback.update(candidate_hash=digest)
                if defect == "stale":
                    feedback["revision"] = 0
                claim["repair"] = feedback
                calls = []
                def api(url, token, path, data=None, **kwargs):
                    calls.append((path, data))
                    if path.endswith("claim/build"):
                        return claim
                    if path == "/artifacts/" + digest:
                        return {"manifest_hash": digest, "files": {**files, "app.js": "tampered"}}
                    return {"state": "PENDING"}
                with patch("graphos.worker._request", side_effect=api), \
                     patch("graphos.worker._eve_environment", return_value={}), \
                     patch("graphos.worker._eve_build") as live:
                    result = build_once("http://localhost:8000", "secret", "run", "eve", reserve=100)
                self.assertEqual(result["status"], "failed")
                self.assertEqual(calls[-1][1]["actual_cost"], 0)
                self.assertIs(calls[-1][1]["cost_known"], True)
                live.assert_not_called()

    def test_live_failure_consumes_reservation_without_fixture(self):
        calls = []
        def api(url, token, path, data=None):
            calls.append((path, data))
            return self.claim(reservation=100) if path.endswith("claim/build") else {"state": "PENDING"}
        with patch("graphos.worker._request", side_effect=api), \
             patch("graphos.worker._eve_environment", return_value={}), \
             patch("graphos.worker._eve_build", side_effect=WorkerError("auth failed")), \
             patch("graphos.worker.fixture_files") as fixture:
            result = build_once("http://localhost:8000", "secret", "run", "eve", reserve=100)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(calls[-1][0].endswith("/fail"))
        self.assertEqual(calls[-1][1]["actual_cost"], 100)
        self.assertIs(calls[-1][1]["cost_known"], False)
        fixture.assert_not_called()

    def test_live_known_overrun_is_reported_truthfully_not_capped(self):
        calls = []
        def api(url, token, path, data=None):
            calls.append((path, data))
            return self.claim(reservation=100) if path.endswith("claim/build") else {"state": "BUDGET_EXCEEDED"}
        with patch("graphos.worker._request", side_effect=api), \
             patch("graphos.worker._eve_environment", return_value={}), \
             patch("graphos.worker._eve_build", side_effect=BuildFailure("overrun", actual_cost=150)):
            result = build_once("http://localhost:8000", "secret", "run", "eve", reserve=100)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(calls[-1][1]["actual_cost"], 150)
        self.assertIs(calls[-1][1]["cost_known"], True)

    def test_adapter_known_error_cost_is_preserved_without_logging_raw_error(self):
        error = {"error": "provider private detail", "cost_known": True, "actual_cost_microdollars": 17}
        with patch("graphos.worker._eve_environment", return_value={}), \
             patch("graphos.worker.run_bounded", return_value=(1, b"", json.dumps(error).encode())):
            with self.assertRaises(BuildFailure) as caught:
                _eve_build(self.claim(), get_profile("static-web"), [])
        self.assertEqual(caught.exception.actual_cost, 17)
        self.assertNotIn("private detail", str(caught.exception))

    def test_adapter_forwards_repair_once_without_mutating_or_truncating_claim(self):
        files = fixture_files()
        feedback = {"candidate_hash": bundle_digest(files), "checks": [
            {"name": "persistence", "passed": False, "detail": "Expected saved task"}]}
        claim = self.claim(repair=feedback)
        repair = {**feedback, "files": files}
        output = {"files": files, "usage": {"actual_cost_microdollars": 0}, "provenance": {"mode": "eve"}}
        with patch("graphos.worker._eve_environment", return_value={}), \
             patch("graphos.worker.run_bounded", return_value=(0, canonical(output), b"")) as runner:
            _eve_build(claim, get_profile("static-web"), [], repair)
        request = json.loads(runner.call_args.kwargs["stdin"])
        self.assertNotIn("repair", request["claim"])
        self.assertEqual(request["repair"], repair)
        self.assertEqual(claim["repair"], feedback)
        self.assertEqual(bundle_digest(request["repair"]["files"]), feedback["candidate_hash"])

    def test_oversized_repair_refuses_before_spawn_and_records_known_zero_cost(self):
        # Each file fits its artifact limit; the serialized request does not.
        for content in ('"\\\n' * 16000, "界" * 20000):
            with self.subTest(kind="escaped" if content.startswith('"') else "non_ascii"):
                files = {name: content for name in ("index.html", "app.js", "styles.css")}
                validate_files(files)
                digest = bundle_digest(files)
                claim = self.claim(reservation=100)
                feedback = {key: claim[key] for key in ("revision", "input_hash", "suite_hash", "policy_hash")}
                feedback.update(candidate_hash=digest, evidence_hash="e" * 64,
                                verifier_attempt_id="prior-verifier", truncated=False,
                                checks=[{"name": "persistence", "passed": False, "detail": "Missing task"}])
                claim["repair"] = feedback
                calls = []
                def api(url, token, path, data=None, **kwargs):
                    calls.append((path, data))
                    if path.endswith("claim/build"):
                        return claim
                    if path == "/artifacts/" + digest:
                        return {"manifest_hash": digest, "files": files}
                    return {"state": "PENDING"}
                with patch("graphos.worker._request", side_effect=api), \
                     patch("graphos.worker._eve_environment", return_value={}), \
                     patch("graphos.worker.run_bounded") as runner:
                    result = build_once("http://localhost:8000", "secret", "run", "eve", reserve=100)
                runner.assert_not_called()
                self.assertEqual(result["status"], "failed")
                self.assertIn("128 KiB", result["reason"])
                self.assertEqual(calls[-1][1]["actual_cost"], 0)
                self.assertIs(calls[-1][1]["cost_known"], True)

    def test_unknown_domains_are_contract_only(self):
        for name in ("games", "bots", "data", "media", "trading-research"):
            self.assertEqual(get_profile(name)["status"], "contract-only")
            with self.assertRaises(ProfileError):
                require_active(name)
        self.assertEqual(default_spec()["requirements"], get_profile("static-web")["acceptance_criteria"])


if __name__ == "__main__":
    unittest.main()
