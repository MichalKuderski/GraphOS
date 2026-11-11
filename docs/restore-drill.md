# Local PostgreSQL and artifact restore drill

`scripts/restore_drill.py` captures the local GraphOS database tables and their
referenced content-addressed objects, restores them into a newly created scratch
database, and compares the restored identities. It never replaces the source
database, starts a restored controller, dispatches work, or deletes a database.

```sh
.venv/bin/python -m scripts.restore_drill --output docs/restore-validation.json
```

The script reads the existing private `.state/local.env` or explicit environment.
It requires `GRAPHOS_DATABASE_URL`, `GRAPHOS_ARTIFACT_ROOT`, a local PostgreSQL 17
source, and the existing `graphos-dev-db` container (`--container` can select
another local container). It verifies that the DSN and container identify the
same PostgreSQL cluster before dumping. It uses the explicit local Docker socket;
ambient remote Docker contexts cannot redirect the drill.

The local database role must be able to export snapshots, inspect the cluster
identifier, read the GraphOS tables and create a scratch database. This is an
administrative local validation procedure, not an application-worker permission.
Do not grant these privileges to generated code or the normal worker roles.

## Capture and validation

1. Open a read-only, repeatable-read transaction and export its snapshot.
2. Fingerprint every `public.graphos_*` table's rows and structural metadata.
3. Run `pg_dump --snapshot` while that exporting transaction remains open.
4. Copy only bundle manifests, their transitive file objects, and JSON evidence
   referenced by tasks, attempts and release history in the same snapshot.
   Verify source object hashes; reject symlinks, unsafe objects, corruption and
   reuse of an existing destination.
5. Create a unique `graphos_restore_drill_<random UUID>` database. The script
   refuses existing targets and has no `DROP`, replacement, or `--clean` path.
6. Restore in one transaction, compare row and schema fingerprints, verify the
   copied bundles/evidence and release-manifest identities, and check that the
   restored event identity sequence cannot collide with existing event IDs.

The snapshot transaction remains open through the dump and referenced-object
copy. Ordinary concurrent inserts do not expand the captured snapshot. Artifact
immutability and retention are required: do not run garbage collection or
manually remove source objects during the capture. A missing/corrupt referenced
object fails the drill rather than producing a passing partial backup.

Private dumps, object copies, process diagnostics and a snapshot-identity file
are retained under a mode-0700 `.state/drills/<id>` directory. Dumps, diagnostics
and metadata are mode 0600; copied immutable objects are mode 0400. The scratch
database is also retained. The public JSON report
contains hashes, counts, scope, limits and the scratch identity, never the DSN,
password, bearer credentials, raw database rows or lease tokens. Retention and
eventual deletion of these drill artifacts are explicit operator tasks; the
script performs no broad cleanup.

## Meaning of a passing result

A pass demonstrates a local restore of the captured GraphOS table rows/schema
and referenced artifacts into a fresh database. The reported duration describes
that observed local run. It is not a production RTO/RPO, remote backup,
point-in-time recovery, encryption/key-recovery test, or regional failure test.
Global database roles/grants, non-GraphOS tables and other databases are excluded.
PostgreSQL sequence state is not MVCC; the drill checks safe restored event-ID
allocation rather than claiming an exact transactional sequence snapshot.

The restored database remains offline from GraphOS workers. A real production
restore must separately fence surviving workers, rotate/revoke credentials as
needed, account for post-snapshot provider charges, and reconcile external
effects before dispatch resumes. This drill does not assert that historical
leases remain safe to reuse or that rolling a database back undoes an external
action.

Focused tests for the scratch-name guards and CAS capture are in
`tests/test_restore_drill.py`. They do not count as the actual database drill;
only the generated `docs/restore-validation.json` records that run's result.

The recorded passing local run captured ten GraphOS tables, eighteen CAS objects
(two bundles and twelve evidence objects), and four release manifests. Its
52,609-byte dump restored with matching row/schema fingerprints and passed the
event-sequence collision check. The earlier ENOSPC failure occurred before a
scratch directory or database was created and is retained in
`restore-infrastructure-failure.json`. These observations describe this local
fixture corpus; they do not expand the general recovery claims above.
