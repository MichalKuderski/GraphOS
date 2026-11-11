"""Focused local guard/CAS tests; the actual DB drill is an explicit separate run."""
import hashlib
import os

import pytest

from graphos.artifacts import ArtifactStore
from scripts.restore_drill import DrillError, copy_referenced_cas, docker_command, scratch_name


def test_scratch_identity_cannot_select_source_or_arbitrary_database():
    source = "graphos"
    for candidate in (source, "postgres", "graphos_restore_drill_existing", "x; DROP DATABASE graphos"):
        with pytest.raises(DrillError):
            scratch_name(source, candidate)
    generated = scratch_name(source)
    assert generated.startswith("graphos_restore_drill_") and generated != source
    with pytest.raises(DrillError):
        scratch_name(generated, generated)


def test_cas_capture_copies_only_referenced_transitive_objects(tmp_path):
    source = ArtifactStore(tmp_path / "source")
    bundle = source.put_bundle({"index.html": "hello", "app.js": "// fixture"})
    evidence = source.put_json({"passed": True, "mode": "fixture"})
    unrelated = source.put_json({"unreferenced": True})
    before = {path.name: path.read_bytes() for path in source.objects.iterdir()}
    result = copy_referenced_cas(source.root, tmp_path / "copy", {bundle}, {evidence})
    assert unrelated not in result["objects"]
    assert len(result["objects"]) == 4
    copied = ArtifactStore(tmp_path / "copy")
    assert copied.get_bundle(bundle) == {"index.html": "hello", "app.js": "// fixture"}
    assert copied.get_json(evidence) == {"passed": True, "mode": "fixture"}
    assert before == {path.name: path.read_bytes() for path in source.objects.iterdir()}


def test_cas_capture_rejects_changed_object_and_never_reuses_destination(tmp_path):
    source = ArtifactStore(tmp_path / "source")
    bundle = source.put_bundle({"app.js": "original"})
    child = source.objects / hashlib.sha256(b"original").hexdigest()
    child.chmod(0o600)
    child.write_bytes(b"altered")
    with pytest.raises(DrillError, match="content verification"):
        copy_referenced_cas(source.root, tmp_path / "copy", {bundle}, set())
    with pytest.raises(DrillError, match="new directory"):
        copy_referenced_cas(source.root, tmp_path / "copy", {bundle}, set())


def test_cas_capture_rejects_symlink_objects(tmp_path):
    source = ArtifactStore(tmp_path / "source")
    evidence = source.put_json({"ok": True})
    path = source.objects / evidence
    other = tmp_path / "outside"
    other.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(other)
    with pytest.raises(OSError):
        copy_referenced_cas(source.root, tmp_path / "copy", set(), {evidence})
    assert other.read_bytes()


def test_container_command_targets_local_daemon_without_shell():
    command = docker_command("graphos-dev-db", ["pg_restore", "--no-owner"])
    assert command[:4] == ["docker", "--host=unix:///var/run/docker.sock", "exec", "-i"]
    assert not any(value in command for value in ("--clean", "--create", "--host=evil"))
    with pytest.raises(DrillError):
        docker_command("db;rm -rf /", [])


def test_snapshot_directory_is_not_created_by_missing_source(tmp_path):
    target = tmp_path / "target"
    with pytest.raises(DrillError):
        copy_referenced_cas(tmp_path / "missing", target, set(), set())
    assert not target.exists()
    assert os.name == "posix"  # Local drill relies on O_NOFOLLOW, like the artifact store.
