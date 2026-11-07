"""Profile admission and real isolated positive/negative inventory verification."""
from pathlib import Path

import pytest

from graphos.profiles import default_spec, fixture_files, get_profile
from graphos.sandbox import verify_bundle
from scripts.acceptance import local_environment


def test_inventory_spec_is_bound_to_its_fixed_product_contract():
    profile = get_profile("local-inventory")
    spec = default_spec("local-inventory")
    assert profile["status"] == "active"
    assert profile["fixture_directory"] == "inventory"
    assert spec["profile"] == "local-inventory"
    assert spec["name"] == "Local inventory"
    assert spec["requirements"] == profile["acceptance_criteria"]
    assert spec["tasks"] == [profile["task_template"]]
    assert spec["suite_hash"] == profile["suite_hash"]
    assert spec["policy_hash"] == profile["policy_hash"]
    assert len(profile["required_checks"]) == len(set(profile["required_checks"]))
    assert {"reject_invalid_input", "unique_item_names", "local_storage_reload",
            "keyboard_operation", "axe_empty", "axe_populated", "visible_focus",
            "mobile_reflow"} <= set(profile["required_checks"])


def test_inventory_fixture_selection_is_separate_from_task_list():
    files = fixture_files("local-inventory")
    profile = get_profile("local-inventory")
    assert set(files) == set(profile["required_files"]) == {"index.html", "app.js", "styles.css"}
    directory = Path(__file__).resolve().parents[1] / "profiles/local-inventory/fixtures/inventory"
    assert files == {name: (directory / name).read_text() for name in files}
    assert files != fixture_files("static-web")


@pytest.fixture
def inventory_sandbox(monkeypatch):
    env = local_environment()
    if not env.get("GRAPHOS_VERIFIER_IMAGE_DIGEST"):
        pytest.skip("A pinned Docker verifier image is required")
    for name in ("GRAPHOS_VERIFIER_IMAGE", "GRAPHOS_VERIFIER_IMAGE_DIGEST"):
        if name in env:
            monkeypatch.setenv(name, env[name])


@pytest.mark.sandbox
def test_inventory_fixture_passes_real_trusted_browser_suite(inventory_sandbox):
    profile = get_profile("local-inventory")
    report = verify_bundle(fixture_files("local-inventory"), profile["acceptance_criteria"],
                           profile_id="local-inventory")
    assert report["passed"], report["checks"]
    assert [check["name"] for check in report["checks"]] == profile["required_checks"]


@pytest.mark.sandbox
def test_inventory_browser_suite_rejects_fractional_quantity_mutant(inventory_sandbox):
    files = fixture_files("local-inventory")
    original = "Number.isSafeInteger(number)"
    assert files["app.js"].count(original) == 1
    files["app.js"] = files["app.js"].replace(original, "Number.isFinite(number)")
    profile = get_profile("local-inventory")
    report = verify_bundle(files, profile["acceptance_criteria"], profile_id="local-inventory")
    assert not report["passed"], "Fractional inventory quantities were incorrectly certified"
    checks = {check["name"]: check for check in report["checks"]}
    assert "reject_invalid_input" in checks, report["checks"]
    assert checks["reject_invalid_input"]["passed"] is False, report["checks"]
