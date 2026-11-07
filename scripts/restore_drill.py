"""Local PostgreSQL/CAS restore drill: read-only source, fresh retained scratch DB.

This does not deploy a restored controller, dispatch work, delete databases,
configure backups, or establish production disaster-recovery objectives.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import time
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from graphos.artifacts import ArtifactStore, validate_digest  # noqa: E402
from scripts.acceptance import local_environment  # noqa: E402

MAX_OBJECT = 1024 * 1024
MAX_COPIED_BYTES = 128 * 1024 * 1024
SCRATCH = re.compile(r"graphos_restore_drill_[0-9a-f]{32}\Z")


class DrillError(RuntimeError):
    """A safe, credential-free drill diagnostic."""


def digest(value) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(data).hexdigest()


def private_json(path: Path, value: dict) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def scratch_name(source_database: str, candidate: str | None = None) -> str:
    name = candidate or "graphos_restore_drill_" + uuid4().hex
    if not SCRATCH.fullmatch(name) or name == source_database:
        raise DrillError("Scratch database must be a distinct generated drill identity")
    return name


def tables(conn) -> list[str]:
    rows = conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' "
                        "AND tablename ~ '^graphos_[a-z0-9_]+$' ORDER BY tablename").fetchall()
    names = [row["tablename"] for row in rows]
    if not {"graphos_runs", "graphos_tasks", "graphos_attempts", "graphos_migrations"}.issubset(names):
        raise DrillError("Source does not contain the expected GraphOS schema")
    return names


def database_fingerprint(conn, names: list[str]) -> dict:
    fingerprints = {}
    for name in names:
        query = sql.SQL("SELECT to_jsonb(t)::text AS record FROM public.{} AS t "
                        "ORDER BY to_jsonb(t)::text COLLATE \"C\"").format(sql.Identifier(name))
        hashed, count = hashlib.sha256(), 0
        with conn.cursor(name="drill_" + uuid4().hex) as cursor:
            cursor.execute(query)
            for row in cursor:
                data = row["record"].encode("utf-8")
                hashed.update(len(data).to_bytes(8, "big"))
                hashed.update(data)
                count += 1
        fingerprints[name] = {"rows": count, "sha256": hashed.hexdigest()}
    columns = conn.execute("""SELECT c.relname AS table_name,a.attname,a.attnum,
        format_type(a.atttypid,a.atttypmod) AS type,a.attnotnull,a.attidentity,a.attgenerated,
        pg_get_expr(d.adbin,d.adrelid) AS default_expression
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        JOIN pg_attribute a ON a.attrelid=c.oid
        LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum
        WHERE n.nspname='public' AND c.relname=ANY(%s) AND a.attnum>0 AND NOT a.attisdropped
        ORDER BY c.relname,a.attnum""", (names,)).fetchall()
    constraints = conn.execute("""SELECT c.relname AS table_name,k.conname,k.contype,
        k.convalidated,pg_get_constraintdef(k.oid) AS definition
        FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relname=ANY(%s)
        ORDER BY c.relname,k.conname""", (names,)).fetchall()
    indexes = conn.execute("SELECT tablename,indexname,indexdef FROM pg_indexes "
                           "WHERE schemaname='public' AND tablename=ANY(%s) "
                           "ORDER BY tablename,indexname", (names,)).fetchall()
    return {"tables": fingerprints,
            "schema_sha256": digest({"columns": columns, "constraints": constraints, "indexes": indexes}),
            "rows_sha256": digest(fingerprints)}


def references(conn) -> tuple[set[str], set[str], list[dict]]:
    bundles, evidence = set(), set()
    for row in conn.execute("SELECT candidate_hash,evidence_hash FROM graphos_tasks").fetchall():
        if row["candidate_hash"]:
            bundles.add(validate_digest(row["candidate_hash"]))
        if row["evidence_hash"]:
            evidence.add(validate_digest(row["evidence_hash"]))
    for row in conn.execute("SELECT candidate_hash,kind,result FROM graphos_attempts").fetchall():
        if row["candidate_hash"]:
            bundles.add(validate_digest(row["candidate_hash"]))
        if row["kind"] == "VERIFY" and isinstance(row["result"], dict) and row["result"].get("evidence_hash"):
            evidence.add(validate_digest(row["result"]["evidence_hash"]))
    releases = conn.execute("SELECT id,manifest_hash,manifest,invalidated_at FROM graphos_releases").fetchall()
    for release in releases:
        if digest(release["manifest"]) != release["manifest_hash"]:
            raise DrillError("A source release manifest does not match its recorded identity")
        for task in release["manifest"]["tasks"]:
            bundles.add(validate_digest(task["candidate_hash"]))
            evidence.add(validate_digest(task["evidence_hash"]))
    return bundles, evidence, releases


def read_object(objects: Path, key: str) -> bytes:
    validate_digest(key)
    if any(path.is_symlink() for path in (objects, *objects.parents)):
        raise DrillError("Source CAS directory must not contain symlink components")
    descriptor = os.open(objects / key, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_OBJECT:
            raise DrillError("Referenced CAS object is not a bounded regular file")
        data = stream.read(MAX_OBJECT + 1)
    if len(data) > MAX_OBJECT or hashlib.sha256(data).hexdigest() != key:
        raise DrillError("Referenced CAS object failed content verification")
    return data


def copy_referenced_cas(source_root: Path, target_root: Path, bundles: set[str], evidence: set[str]) -> dict:
    source_objects = source_root / "objects"
    if not source_objects.is_dir() or target_root.exists():
        raise DrillError("Source CAS must exist and destination must be a new directory")
    target_root.mkdir(mode=0o700)
    target_objects = target_root / "objects"
    target_objects.mkdir(mode=0o700)
    copied, total = {}, 0

    def copy(key: str) -> bytes:
        nonlocal total
        data = read_object(source_objects, key)
        if key in copied:
            return data
        total += len(data)
        if total > MAX_COPIED_BYTES:
            raise DrillError("Local drill CAS byte limit exceeded")
        descriptor = os.open(target_objects / key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        copied[key] = len(data)
        return data

    for key in sorted(bundles):
        manifest = json.loads(copy(key))
        if manifest.get("kind") != "bundle" or not isinstance(manifest.get("files"), list):
            raise DrillError("Referenced bundle manifest has invalid shape")
        for entry in manifest["files"]:
            copy(validate_digest(entry["sha256"]))
    for key in sorted(evidence):
        copy(key)
    restored = ArtifactStore(target_root)
    for key in bundles:
        restored.get_bundle(key)
    for key in evidence:
        restored.get_json(key)
    return {"objects": dict(sorted(copied.items())), "bytes": total,
            "object_set_sha256": digest(copied), "bundle_count": len(bundles),
            "evidence_count": len(evidence)}


def docker_environment() -> dict[str, str]:
    selectors = {"DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"}
    return {key: value for key, value in os.environ.items() if key not in selectors}


def docker_command(container: str, args: list[str]) -> list[str]:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}", container):
        raise DrillError("Invalid local PostgreSQL container name")
    return ["docker", "--host=unix:///var/run/docker.sock", "exec", "-i", container, *args]


def run_drill(dsn: str, artifact_root: Path, *, container: str = "graphos-dev-db") -> dict:
    started, started_at = time.monotonic(), datetime.now(timezone.utc).isoformat()
    connection = conninfo_to_dict(dsn)
    if connection.get("host") not in {"127.0.0.1", "localhost", "::1"}:
        raise DrillError("This drill accepts only an explicitly local PostgreSQL source")
    if not artifact_root.is_dir():
        raise DrillError("Source artifact directory is missing; no source directory was created")
    directory = ROOT / ".state" / "drills" / uuid4().hex
    directory.mkdir(parents=True, mode=0o700)
    directory.chmod(0o700)
    if shutil.disk_usage(directory).free < 256 * 1024 * 1024:
        raise DrillError("Insufficient free space for the bounded local drill")
    archive = directory / "graphos.dump"
    errors = directory / "private-process.log"
    error_fd = os.open(errors, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(error_fd, "wb") as error_log, psycopg.connect(dsn, row_factory=dict_row) as source:
        source.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        identity = source.execute("SELECT current_database() AS database,current_user AS role, "
                                  "current_setting('server_version_num')::int AS version, "
                                  "system_identifier::text AS cluster FROM pg_control_system()").fetchone()
        if identity["version"] // 10000 != 17:
            raise DrillError("This local drill is validated for PostgreSQL 17 only")
        args = ["psql", "--no-psqlrc", "-U", identity["role"], "-d", identity["database"],
                "-Atc", "SELECT system_identifier::text FROM pg_control_system()"]
        cluster = subprocess.run(docker_command(container, args), env=docker_environment(),
                                 stdout=subprocess.PIPE, stderr=error_log, timeout=20, check=False)
        if cluster.returncode or cluster.stdout.decode().strip() != identity["cluster"]:
            raise DrillError("Local container and source DSN do not identify the same PostgreSQL cluster")
        target = scratch_name(identity["database"])
        snapshot = source.execute("SELECT pg_export_snapshot() AS snapshot").fetchone()["snapshot"]
        names = tables(source)
        source_fingerprint = database_fingerprint(source, names)
        bundles, evidence, release_rows = references(source)
        archive_fd = os.open(archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(archive_fd, "wb") as dump:
            args = ["pg_dump", "-U", identity["role"], "-d", identity["database"], "--format=custom",
                    "--no-owner", "--no-privileges", "--table=public.graphos_*", "--snapshot", snapshot]
            dumped = subprocess.run(docker_command(container, args), env=docker_environment(),
                                    stdout=dump, stderr=error_log, timeout=120, check=False)
        if dumped.returncode:
            raise DrillError("Snapshot pg_dump failed; private process log retained")
        # Exporting transaction remains open until pg_dump and all CAS reads finish.
        cas = copy_referenced_cas(artifact_root, directory / "artifacts", bundles, evidence)
        snapshot_identity = {"database": source_fingerprint, "cas": cas,
                             "dump_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                             "exported_snapshot": snapshot, "scratch_database": target,
                             "source_database": identity["database"]}
        private_json(directory / "snapshot-identity.json", snapshot_identity)
    # A unique database is created without a replace/clean/drop path. Any collision fails.
    with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as admin:
        if admin.execute("SELECT 1 FROM pg_database WHERE datname=%s", (target,)).fetchone():
            raise DrillError("Generated scratch database already exists; refusing to reuse it")
        admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(target)))
    with archive.open("rb") as dump, errors.open("ab") as error_log:
        args = ["pg_restore", "-U", identity["role"], "-d", target, "--exit-on-error",
                "--single-transaction", "--no-owner", "--no-privileges"]
        restored = subprocess.run(docker_command(container, args), env=docker_environment(),
                                  stdin=dump, stdout=error_log, stderr=error_log, timeout=120, check=False)
    if restored.returncode:
        raise DrillError("Restore into retained scratch database failed; private process log retained")
    restored_dsn = make_conninfo(dsn, dbname=target)
    with psycopg.connect(restored_dsn, row_factory=dict_row) as restored_conn:
        restored_conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        restored_names = tables(restored_conn)
        restored_fingerprint = database_fingerprint(restored_conn, restored_names)
        if names != restored_names or source_fingerprint != restored_fingerprint:
            raise DrillError("Restored rows or schema differ from the exported source snapshot")
        restored_bundles, restored_evidence, restored_releases = references(restored_conn)
        if bundles != restored_bundles or evidence != restored_evidence or len(release_rows) != len(restored_releases):
            raise DrillError("Restored artifact/release references differ from the exported snapshot")
        restored_store = ArtifactStore(directory / "artifacts")
        for key in restored_bundles:
            restored_store.get_bundle(key)
        for key in restored_evidence:
            restored_store.get_json(key)
        max_event = restored_conn.execute("SELECT coalesce(max(id),0) AS value FROM graphos_events").fetchone()["value"]
        sequence = restored_conn.execute("SELECT last_value,is_called FROM graphos_events_id_seq").fetchone()
        next_value = sequence["last_value"] + int(sequence["is_called"])
        if next_value <= max_event:
            raise DrillError("Restored event identity sequence could collide with existing events")
    report = {
        "schema_version": 1, "status": "PASS", "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "duration_ms": round((time.monotonic() - started) * 1000),
        "scope": "Local PostgreSQL 17 graphos_* tables plus referenced CAS; no restored service dispatch",
        "source_read_only": True, "source_snapshot_held_through_dump_and_cas_copy": True,
        "scratch_database": target, "scratch_retained": True, "private_drill_directory": str(directory),
        "source_snapshot_identity_sha256": digest(snapshot_identity),
        "source_rows_sha256": source_fingerprint["rows_sha256"],
        "restored_rows_sha256": restored_fingerprint["rows_sha256"],
        "schema_sha256": source_fingerprint["schema_sha256"],
        "table_row_counts": {name: item["rows"] for name, item in source_fingerprint["tables"].items()},
        "cas_object_set_sha256": cas["object_set_sha256"], "cas_objects": len(cas["objects"]),
        "cas_bytes": cas["bytes"], "bundles_verified": len(bundles), "evidence_objects_verified": len(evidence),
        "release_manifests_verified": len(release_rows), "event_sequence_collision_check": "PASS",
        "dump_bytes": archive.stat().st_size,
        "limitations": ["Local same-cluster scratch restore, not remote or regional disaster recovery",
                        "No RPO/RTO target established; duration is an observed local drill",
                        "No backup encryption, key recovery, scheduled backup or PITR tested",
                        "Non-GraphOS tables, global roles/grants and other databases excluded",
                        "No dispatch resumed; surviving workers and post-snapshot external effects need reconciliation",
                        "Sequences are non-MVCC; only restored event-sequence collision safety was checked",
                        "No garbage collection may remove referenced immutable objects during capture"],
    }
    private_json(directory / "result.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", default="graphos-dev-db")
    parser.add_argument("--output", type=Path, default=ROOT / "docs" / "restore-validation.json")
    args = parser.parse_args()
    env = local_environment()
    if not env.get("GRAPHOS_DATABASE_URL") or not env.get("GRAPHOS_ARTIFACT_ROOT"):
        parser.error("GRAPHOS_DATABASE_URL and GRAPHOS_ARTIFACT_ROOT are required")
    try:
        report = run_drill(env["GRAPHOS_DATABASE_URL"], Path(env["GRAPHOS_ARTIFACT_ROOT"]), container=args.container)
    except Exception as exc:
        report = {"schema_version": 1, "status": "FAIL", "error_type": type(exc).__name__,
                  "error": str(exc) if isinstance(exc, DrillError) else "Drill operation failed; source was not replaced",
                  "production_disaster_recovery_established": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "output": str(args.output),
                      "scratch_database": report.get("scratch_database"), "error": report.get("error")}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
