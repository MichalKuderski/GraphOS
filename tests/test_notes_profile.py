"""Real Docker/browser contract and negative controls for offline notes.

These are verifier calibration tests, not estimates of model quality. No model
calls are made and no candidate JavaScript runs on the host.
"""
import pytest

from graphos.profiles import fixture_files, get_profile
from graphos.sandbox import verify_bundle
from scripts.acceptance import local_environment


@pytest.fixture(scope="module")
def notes_configuration():
    env = local_environment()
    if not env.get("GRAPHOS_VERIFIER_IMAGE_DIGEST"):
        pytest.skip("Real Docker verifier configuration unavailable: GRAPHOS_VERIFIER_IMAGE_DIGEST")
    return {key: value for key, value in env.items()
            if key in ("GRAPHOS_VERIFIER_IMAGE", "GRAPHOS_VERIFIER_IMAGE_DIGEST")}


def verify_notes(files, configuration, monkeypatch):
    for key, value in configuration.items():
        monkeypatch.setenv(key, value)
    profile = get_profile("local-notes")
    return verify_bundle(files, profile["acceptance_criteria"], profile_id="local-notes")


@pytest.mark.sandbox
def test_notes_fixture_satisfies_behavior_and_accessibility(notes_configuration, monkeypatch):
    report = verify_notes(fixture_files("local-notes"), notes_configuration, monkeypatch)
    assert report["passed"], [check for check in report["checks"] if not check["passed"]]
    assert [check["name"] for check in report["checks"]] == get_profile("local-notes")["required_checks"]


@pytest.mark.sandbox
@pytest.mark.parametrize(("before", "after", "failed_check"), [
    ("localStorage.setItem(STORAGE_KEY, JSON.stringify(nextNotes));", "/* Persistence disabled. */", "local_storage_reload"),
    ("notes.map(note => note.id === editingId ? { ...note, title, body } : note)",
     "[...notes, { id: crypto.randomUUID(), title, body }]", "edit_note"),
    ("(note.title + '\\n' + note.body).toLocaleLowerCase()", "note.title.toLocaleLowerCase()", "search_notes"),
    ("heading.textContent = note.title;", "heading.innerHTML = note.title;", "literal_html_input"),
    ("if (!title || !body) {", "if ((!title || !body) && editingId === null) {", "reject_empty_input"),
])
def test_notes_verifier_rejects_semantic_regressions(
        before, after, failed_check, notes_configuration, monkeypatch):
    files = fixture_files("local-notes")
    assert files["app.js"].count(before) == 1, "Negative control no longer matches the fixture"
    files["app.js"] = files["app.js"].replace(before, after)
    report = verify_notes(files, notes_configuration, monkeypatch)
    assert report["passed"] is False, report
    failures = {check["name"] for check in report["checks"] if not check["passed"]}
    assert failed_check in failures, [check for check in report["checks"] if not check["passed"]]
