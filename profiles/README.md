# Execution profile assets

The active `static-web` profile certifies the fixed task-list contract in
`static-web/profile.json`. Its eight disclosed browser checks cover accessible
structure, adding, completing, filtering, deleting, localStorage/reload, empty
input and literal HTML-looking input. It does not certify arbitrary websites,
backends, trading systems or additional requirements. Other domain profiles are
contract-only and cannot execute.

The task-list fixture under `static-web/fixtures/` is deterministic test data.
Fixture mode records `provenance.mode = "fixture"` and is never selected as a
fallback when the separate live eve adapter lacks authentication or fails.

From a source checkout, the runtime locates `profiles/`, `verifier/` and
`agents/eve/dist/src/cli.js` relative to the checkout. A wheel alone does not ship
these deployment assets. For a packaged or container deployment, set
`GRAPHOS_RUNTIME_ROOT` to an absolute, trusted deployment directory containing
those assets. The application container uses `/app`. This setting is operator
configuration; candidate output and task requests cannot change it.

Verification requires the prebuilt `GRAPHOS_VERIFIER_IMAGE` and its exact local
`GRAPHOS_VERIFIER_IMAGE_DIGEST` (`sha256:…`). The digest is included in the policy
hash and compared with Docker's inspection result before execution. Rebuilding
the image requires updating the pin and admitting a specification with the new
policy. The fixed suite's source and Dockerfile are included in the suite hash.

Candidate files run only in Chromium inside a constrained Docker container:
network disabled, non-root UID, read-only filesystem, read-only candidate and
trusted-suite mounts, dropped capabilities, no new privileges, bounded processes,
CPU, memory, output and time. A fresh empty Docker client configuration and an
explicit local Unix socket prevent inherited remote contexts and proxy settings.
Broker credentials and the Docker socket are never mounted into the container.
Chromium's separate process sandbox is disabled; the Docker boundary is the
isolation mechanism. This is not a VM boundary or a proof against browser/kernel
vulnerabilities. Missing Docker, an incorrect image pin, malformed files or a
failed check block acceptance.

Artifact storage assumes its root is controlled by the operator. It rejects
candidate traversal, symlink destinations, unsafe names, type and size violations,
and verifies content hashes on reads. It is not a defense against an administrator
who can rewrite the application, trusted verifier, or storage directory.
