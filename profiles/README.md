# Execution profile assets

Three fixed contracts are active: `static-web` v2 (task lists), `local-notes`
v1 (notes), and `local-inventory` v1 (inventory). Each produces exactly
`index.html`, `app.js`, and `styles.css`. Registered objectives, requirements,
and selectors are declared in each profile's `profile.json`; unrelated objectives
and additional requirements are rejected at admission.

Their browser suites cover product behavior, localStorage/reload, input
validation, literal user text, keyboard operation, automated axe-core accessibility,
visible focus, and 320/390 CSS pixel reflow. Axe violations and incomplete findings
block acceptance. These finite checks do not certify full WCAG conformance,
arbitrary websites, backends, or resistance to deliberate test gaming. Other
domain profiles remain contract-only and cannot execute.

Each fixture directory contains deterministic test data. Fixture mode records
`provenance.mode = "fixture"` and is never selected as an authentication or model
failure fallback. `python -m graphos submit --profile local-notes` selects a
registered product contract; `execute` still requires an explicit builder mode.

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
policy. The complete trusted verifier asset tree, including product checks, accessibility helpers, vendored axe engine, and Dockerfile, is included in the suite hash. The host copies and rechecks every asset before mounting the immutable snapshot read-only.

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

On the managed workspace's Docker VFS driver, run browser verification serially.
Container creation duplicates large image layers; concurrent verification can
exhaust disk before browser startup. Deployment admission and host resource
scheduling remain required production work.
