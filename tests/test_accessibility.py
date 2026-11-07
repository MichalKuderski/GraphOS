"""Finite accessibility gates, including real-browser negative controls in Docker.

The host only creates fixture bytes and validates reports. Candidate JavaScript
and axe execute exclusively in an offline, unprivileged browser container.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid

import pytest

from graphos.sandbox import run_bounded
from verifier.accessibility import AXE_VERSION, validate_axe_report


ROOT = Path(__file__).resolve().parents[1]


def _report(**changes):
    return {"version": AXE_VERSION, "violations": [], "incomplete": [],
            "passes": [{"id": "color-contrast"}], "inapplicable": [], **changes}


def test_incomplete_contrast_is_not_passing_evidence():
    with pytest.raises(AssertionError, match="incomplete:color-contrast"):
        validate_axe_report(_report(incomplete=[{"id": "color-contrast", "nodes": [
            {"target": [".completed"]}]}]), "completed")


def test_unresolved_noncontrast_findings_also_fail_closed():
    with pytest.raises(AssertionError, match="incomplete:label"):
        validate_axe_report(_report(incomplete=[{"id": "label", "nodes": []}]), "empty")


@pytest.mark.parametrize("changes,reason", [
    ({"version": "untrusted"}, "engine version"),
    ({"passes": []}, "omitted.*color-contrast"),
    ({"incomplete": None}, "Missing axe incomplete"),
    ({"violations": [{"id": "button-name", "nodes": []}]}, "violations:button-name"),
])
def test_invalid_or_failed_audit_is_rejected(changes, reason):
    with pytest.raises(AssertionError, match=reason):
        validate_axe_report(_report(**changes), "empty")


def test_axe_asset_matches_recorded_upstream_integrity():
    directory = ROOT / "verifier" / "vendor" / "axe-core"
    provenance = json.loads((directory / "provenance.json").read_text())
    assert provenance["version"] == AXE_VERSION
    assert provenance["integrity_verified"] is True
    assert provenance["integrity"].startswith("sha512-")
    assert provenance["tarball"] == f"https://registry.npmjs.org/axe-core/-/axe-core-{AXE_VERSION}.tgz"
    for name, digest in provenance["files_sha256"].items():
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == digest


PROBE = '''
import json, sys, threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, '/verifier')
from accessibility import static_web_accessibility_checks
from playwright.sync_api import sync_playwright
class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_): pass
server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory='/cases'))
threading.Thread(target=server.serve_forever, daemon=True).start()
origin = f'http://127.0.0.1:{server.server_port}'
spec = json.load(open('/cases/spec.json'))
checks = dict(static_web_accessibility_checks())
results = []
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True, chromium_sandbox=False,
        args=['--disable-dev-shm-usage'])
    for case in spec:
        for name in case['checks']:
            context = browser.new_context(viewport={'width': 1024, 'height': 768},
                                          service_workers='block')
            page = context.new_page()
            page.set_default_timeout(2500)
            page.set_default_navigation_timeout(5000)
            page.route('**/*', lambda route: route.continue_()
                       if route.request.url.startswith(origin + '/') else route.abort())
            try:
                page.goto(origin + '/' + case['name'] + '/index.html', wait_until='domcontentloaded')
                checks[name](page)
                results.append({'case': case['name'], 'check': name, 'passed': True, 'detail': ''})
            except Exception as exc:
                results.append({'case': case['name'], 'check': name, 'passed': False,
                                'detail': str(exc).split('Call log:')[0][:1000]})
            finally:
                context.close()
    browser.close()
server.shutdown()
server.server_close()
print(json.dumps(results))
'''


@pytest.fixture(scope="module")
def accessibility_browser_results():
    if shutil.which("docker") is None:
        pytest.skip("Docker verifier image unavailable")
    # Never pass provider keys, DB secrets, or proxy credentials to the verifier.
    env = {key: value for key, value in os.environ.items() if key in {"PATH", "LANG", "LC_ALL"}}
    image = os.environ.get("GRAPHOS_VERIFIER_IMAGE", "graphos-verifier:local")
    fixture = ROOT / "profiles" / "static-web" / "fixtures" / "task-list"
    files = {path.name: path.read_text() for path in fixture.iterdir() if path.is_file()}
    spec = [
        {"name": "valid", "checks": ["axe_empty", "axe_populated", "axe_completed",
                                       "keyboard_operation", "visible_focus", "mobile_reflow"]},
        {"name": "red_delete", "checks": ["axe_populated"],
         "css": "li button{color:#fff;background:#f87171}"},
        {"name": "gray_completed", "checks": ["axe_completed"],
         "css": "input:checked+span{color:#94a3b8;background:#f8fafc}"},
        {"name": "missing_label", "checks": ["axe_empty"], "unlabel": True},
        {"name": "hidden_focus", "checks": ["visible_focus"],
         "css": "*:focus,*:focus-visible{outline:none!important}"},
        {"name": "weak_focus", "checks": ["visible_focus"],
         "css": "*:focus,*:focus-visible{outline:3px solid #eee!important}"},
        {"name": "keyboard_trap", "checks": ["keyboard_operation"],
         "js": "document.addEventListener('keydown',e=>{if(e.key==='Tab')e.preventDefault()})"},
        {"name": "keyboard_activation", "checks": ["keyboard_operation"],
         "js": "document.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' ')e.preventDefault()})"},
        {"name": "wide_layout", "checks": ["mobile_reflow"], "css": "main{min-width:1000px}"},
        {"name": "clipped_text", "checks": ["mobile_reflow"],
         "css": "body{overflow-x:hidden}li label span{white-space:nowrap}"},
        {"name": "incomplete_contrast", "checks": ["axe_populated"],
         "css": "li button{color:#111;background:linear-gradient(45deg,#000,#fff)}"},
    ]
    with tempfile.TemporaryDirectory(prefix="graphos-a11y-") as temporary:
        directory = Path(temporary)
        # Docker's unprivileged UID must traverse these fixture-only directories.
        directory.chmod(0o755)
        cases = directory / "cases"
        cases.mkdir()
        cases.chmod(0o755)
        for case in spec:
            candidate = cases / case["name"]
            candidate.mkdir()
            candidate.chmod(0o755)
            for name, original in files.items():
                content = original
                if name == "styles.css":
                    content += "\n" + case.get("css", "")
                if name == "app.js":
                    content += "\n" + case.get("js", "")
                if name == "index.html" and case.get("unlabel"):
                    content = content.replace('for="new-task"', '')
                (candidate / name).write_text(content)
                (candidate / name).chmod(0o444)
        (cases / "spec.json").write_text(json.dumps(spec))
        (cases / "spec.json").chmod(0o444)
        probe = directory / "probe.py"
        probe.write_text(PROBE)
        probe.chmod(0o444)
        trusted = directory / "verifier"
        shutil.copytree(ROOT / "verifier", trusted, ignore=shutil.ignore_patterns("__pycache__"))
        trusted.chmod(0o755)
        for path in trusted.rglob("*"):
            path.chmod(0o755 if path.is_dir() else 0o444)
        config = directory / "docker-config"
        config.mkdir(mode=0o700)
        docker = ["docker", "--host", "unix:///var/run/docker.sock", "--config", str(config)]
        code, stdout, _ = run_bounded([*docker, "image", "inspect", "--format", "{{.Id}}", image],
                                      timeout=15, output_limit=65536, env=env)
        if code:
            pytest.skip("Pinned local Docker verifier image unavailable")
        image_id = stdout.decode().strip()
        assert image_id.startswith("sha256:") and len(image_id) == 71
        container = "graphos-a11y-test-" + uuid.uuid4().hex
        command = [*docker, "run", "--rm", "--name", container, "--network", "none",
                   "--user", "10001:10001", "--read-only", "--security-opt", "no-new-privileges",
                   "--cap-drop", "ALL", "--pids-limit", "128", "--cpus", "1.0",
                   "--memory", "768m", "--memory-swap", "768m", "--shm-size", "128m",
                   "--tmpfs", "/tmp:rw,nosuid,nodev,size=128m", "--workdir", "/tmp",
                   "--mount", f"type=bind,src={cases},dst=/cases,readonly",
                   "--mount", f"type=bind,src={trusted},dst=/verifier,readonly",
                   "--mount", f"type=bind,src={probe},dst=/probe.py,readonly"]
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
                     "http_proxy", "https_proxy", "all_proxy", "no_proxy"):
            command.extend(("--env", name + "="))
        command.extend(("--entrypoint", "python", image_id, "-I", "/probe.py"))
        try:
            code, stdout, stderr = run_bounded(command, timeout=180, output_limit=1_048_576, env=env)
            assert code == 0, stderr.decode(errors="replace")[-2000:]
            results = json.loads(stdout)
            assert len(results) == sum(len(case["checks"]) for case in spec)
            return {(result["case"], result["check"]): result for result in results}
        finally:
            run_bounded([*docker, "rm", "--force", container], timeout=10, output_limit=65536, env=env)


@pytest.mark.sandbox
@pytest.mark.parametrize("check", ["axe_empty", "axe_populated", "axe_completed",
                                   "keyboard_operation", "visible_focus", "mobile_reflow"])
def test_valid_static_fixture_passes_accessibility(accessibility_browser_results, check):
    result = accessibility_browser_results[("valid", check)]
    assert result["passed"], result


@pytest.mark.sandbox
@pytest.mark.parametrize("case,check,reason", [
    ("red_delete", "axe_populated", "violations:color-contrast"),
    ("gray_completed", "axe_completed", "violations:color-contrast"),
    ("missing_label", "axe_empty", "violations:label"),
    ("hidden_focus", "visible_focus", "focus requires a visible outline"),
    ("weak_focus", "visible_focus", "outline contrast is below 3:1"),
    ("keyboard_trap", "keyboard_operation", "cannot be reached with Tab"),
    ("keyboard_activation", "keyboard_operation", "Locator expected to be visible"),
    ("wide_layout", "mobile_reflow", "Mobile reflow failed"),
    ("clipped_text", "mobile_reflow", "Mobile reflow failed"),
    ("incomplete_contrast", "axe_populated", "incomplete:color-contrast"),
])
def test_defective_fixture_is_rejected_for_the_expected_reason(
        accessibility_browser_results, case, check, reason):
    result = accessibility_browser_results[(case, check)]
    assert not result["passed"], result
    assert reason in result["detail"], result
