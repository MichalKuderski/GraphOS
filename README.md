# GraphOS

GraphOS turns a versioned task specification into artifacts that can be delivered
only with current verification evidence. Models propose outputs; the controller
enforces state, budgets, authority, and acceptance.

**Status: a bounded, single-tenant platform with three offline application
profiles implemented.** The current source supports a task list, local notes,
and local inventory. Validation of the expanded suites and the new live pilot is
pending; implemented scope is not a measured success rate.

An earlier task-list revision completed a real model build and a controlled
persistence repair. Both passed their eight-check suite. Separate product review
then found low text contrast that those checks missed; the current revision adds
automated accessibility gates. Earlier passes do not certify the new revision.
See [live evidence](docs/live-validation.md), the
[validation summary](docs/validation-summary.md), and
[production readiness](docs/production-readiness.md) for measured results,
retained failures, and outstanding production gates.

## Implemented

- PostgreSQL admission, versioned specifications, DAG scheduling, transactions,
  leases, fencing, bounded retries, event history, and transactional outbox records.
- Independent builder/verifier credentials and lease-scoped artifact access.
- Content-addressed artifacts with hash verification and strict path/size rules.
- Candidate/input/suite/policy-bound evidence; revisions invalidate prior work.
- Profile-specific Playwright suites running in a constrained, network-disabled
  Docker container. The full trusted verifier asset tree, including pinned
  axe-core 4.14.0, is hashed and copied read-only. Generated code never executes
  directly on the host.
- Release manifests, cancellation, explicit unknown external-effect state, and
  fenced reconciliation. No external deployment or trading adapter is enabled.
- Integer-microdollar reservations, conservative unknown-cost handling, and
  truthful overrun incidents that block new dispatch.
- A real eve agent adapter with typed outputs and no model-accessible tools.
- Scoped repair context from the latest rejected candidate and its verifier
  diagnostics; every replacement needs new independent evidence.
- An operator dashboard and a CLI for reproducible execution and artifact export.

The active profiles are disclosed, fixed product contracts:

| Profile | Implemented application scope |
|---|---|
| `static-web` v2 | Task creation, completion, filtering, deletion, localStorage persistence, and literal treatment of user text |
| `local-notes` v1 | Title/body creation and editing, canceling edits, search, deletion, validation, and localStorage persistence |
| `local-inventory` v1 | Unique item names, validated integer quantities, quantity updates, search, deletion, and localStorage persistence |

Each produces only `index.html`, `app.js`, and `styles.css`. There is no backend,
account system, synchronization, package installation, or external network use.
Browser storage is not a managed database or backup. Arbitrary objectives and
extra requirements remain inadmissible until a trusted contract and grader exist.
Games, bots, data, media, and trading research remain **contract-only** and cannot
execute.

Current suites audit empty and populated states with axe-core; the task-list
suite also audits completed tasks. Any reported violation or incomplete finding
blocks acceptance. Additional gates check keyboard operation and reachability,
visible focus, and mobile reflow at 320 and 390 CSS pixels. These finite checks
do not certify full WCAG conformance, assistive-technology usability, or every
interaction state; manual accessibility and product review remain necessary.

## Local setup

Requires Linux, Python 3.12+, Docker with the local Unix socket, and Node 24 for the eve
adapter. Setup provisions a real local PostgreSQL database, generates distinct
private role credentials, builds the verifier, and records its immutable image
identity. It does not make model calls, delete existing volumes, or deploy online.

```bash
python3 scripts/setup.py --with-agent
.venv/bin/python -m graphos --env-file .state/local.env serve --port 8030
```

Open http://127.0.0.1:8030. The operator token is in the private
`.state/local.env` file. Enter it in the dashboard; it stays in browser memory
only. The service binds localhost by default. Do not expose it publicly without
the deployment controls in the readiness document.

In another terminal, run the complete deterministic platform demonstration:

```bash
.venv/bin/python -m graphos --env-file .state/local.env demo --builder fixture --profile static-web
```

This mode builds a declared test fixture and runs the real independent browser
suite. It proves platform integration behavior, **not AI generation quality**.
It never becomes an automatic fallback when model authentication fails.
Use `--profile local-notes` or `--profile local-inventory` to select the other
implemented contracts.

```bash
.venv/bin/python -m graphos --env-file .state/local.env export RUN_ID ./delivered-app
.venv/bin/python -m graphos --env-file .state/local.env doctor
```

The exported directory contains a release manifest and application files. Open
the application through a local static server on a separate origin from the
control plane. Candidate HTML is not embedded in the dashboard.

## Live model mode

See [the eve adapter instructions](agents/eve/README.md). It runs as a separate
authenticated local server. Gateway credentials stay server-side. The builder
uses only its dedicated eve token; the verifier receives neither model nor
release credentials.

Configure and verify a dedicated Gateway credential and spending budget before
enabling live calls. Gateway budgets are **soft caps**: an in-flight request can
cross a threshold, and updates may be delayed. The implementation-session
authorization is **$5 total**, including earlier failures and experiments.
Reconcile cumulative spend before each new batch. Local reservations control
dispatch but do not prove a hard provider invoice ceiling. Unknown or
over-reservation cost blocks further work; late charges require reconciliation.

After configuring the server and its controls:

```bash
.venv/bin/python scripts/live_acceptance.py --execute --profile static-web --max-attempts 1 --budget 1000000
```

No API key belongs in source control or chat. `.state/`, environment files,
sessions, generated outputs, and dependencies are ignored by Git.
The explicit live harness rebuilds the adapter, records the attempt and usage,
runs independent verification, and exports only an accepted candidate. A new
profile or suite revision needs new evidence; it cannot inherit an old pass.

## Validation

```bash
.venv/bin/python scripts/check.py
.venv/bin/python scripts/evaluate_profiles.py calibrate
cd agents/eve
npm run typecheck
npm test
npm run build
npm run test:runtime
```

Database tests use their own schemas. The managed acceptance harness launches and
restarts its own API, uses actual PostgreSQL and the pinned browser container,
and records explicit PASS/FAIL/BLOCKED outcomes. Grader calibration checks valid
fixtures and deliberately defective artifacts; it does not measure model quality.
Live model testing is separate and off by default. The
[profile pilot](docs/evaluation-pilot.md) retains every dispatched trial and
reports per-profile outcomes, but uses disclosed contracts rather than held-out
projects. No pilot result is claimed here until its recorded run exists.
[Evaluation protocol](evals/protocol.json) defines the later matched-budget,
repeated-run comparisons needed before superiority claims.

## Architecture and operating limits

- [Foundation blueprint](docs/foundation/blueprint.html) — the original research
  and design, retained as a historical proposal rather than a completion claim.
- [Implementation contract](IMPLEMENTATION_CONTRACT.md).
- [Validation plan](docs/validation-plan.md).
- [Production-readiness ledger](docs/production-readiness.md).
- [Implementation roadmap](docs/implementation-roadmap.md).
- [Operational runbook](docs/operations.md).

The first deployment model is one operator/tenant with trusted worker services.
Role authentication does not provide multi-tenant identity management, and a
trusted verifier credential is not a hardware attestation of test execution.
Docker is a constrained execution boundary, not a guarantee against kernel or
browser vulnerabilities. The Chromium process sandbox is disabled inside that
container and this is recorded in policy/evidence. Use stronger dedicated
isolation before exposing arbitrary hostile workloads to a shared production host.

No software or finite test suite can guarantee 100% accuracy, reliability, or
consistency over every timeframe. GraphOS records what passed, what changed, and
what remains unverified so that its operating claims can be audited.

The next promotion gates are grader calibration and repeated live trials,
untouched representative benchmarks, manual accessibility review, provider and
worker failure tests, load/soak operation, and production recovery. Multi-tenant
identity and authorization, worker isolation, credential lifecycle, and independent
security review precede public or hostile workloads. Games, bots, analytical
projects, media, and trading research each need their own tools, domain graders,
and operating controls before their profiles can be enabled.
