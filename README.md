# GraphOS

GraphOS turns a versioned task specification into artifacts that can be delivered
only with current verification evidence. Models propose outputs; the controller
enforces state, budgets, authority, and acceptance.

**Status: first bounded execution milestone implemented and locally verified.** This is a working
self-hosted control plane with a deliberately narrow task-list web-application
profile. It is not a completed universal agent platform. Live model generation,
long-horizon reliability, and comparative model quality have not yet been
validated. See [production readiness](docs/production-readiness.md) and the
[acceptance results](evals/results/pytest-acceptance.json).
The [validation summary](docs/validation-summary.md) identifies measured results
and their limits, including retained infrastructure failures.

## Implemented

- PostgreSQL admission, versioned specifications, DAG scheduling, transactions,
  leases, fencing, bounded repair, event history, and transactional outbox records.
- Independent builder/verifier credentials and lease-scoped artifact access.
- Content-addressed artifacts with hash verification and strict path/size rules.
- Candidate/input/suite/policy-bound evidence; revisions invalidate prior work.
- A fixed trusted Playwright suite running in a constrained, network-disabled
  Docker container. Generated code never executes directly on the host.
- Release manifests, cancellation, explicit unknown external-effect state, and
  fenced reconciliation. No external deployment or trading adapter is enabled.
- Integer-microdollar reservations, conservative unknown-cost handling, and
  truthful overrun incidents that block new dispatch.
- A real eve agent adapter with typed outputs and no model-accessible tools.
- An operator dashboard and a CLI for reproducible execution and artifact export.

The `static-web` profile currently means one disclosed task-list application
contract: add, complete, filter, delete, persistence, empty-input handling, and
literal treatment of HTML-looking input. Its objective and behavioral criteria
are fixed. Games, bots, data, media and trading research have **contract-only**
profiles; admission blocks them until implementations and domain graders exist.

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
.venv/bin/python -m graphos --env-file .state/local.env demo --builder fixture
```

This mode builds a declared test fixture and runs the real independent browser
suite. It proves platform integration behavior, **not AI generation quality**.
It never becomes an automatic fallback when model authentication fails.

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

Configure a dedicated Gateway credential with a provider-enforced spending
limit before enabling live calls. The implementation-session authorization is
**$5 total**. A local acknowledgment or budget reservation is not proof of a
provider-enforced invoice limit. Unknown or over-reservation cost blocks further
work; late provider billing still requires operational reconciliation.

After configuring the server and its controls:

```bash
.venv/bin/python -m graphos --env-file .state/local.env demo --builder eve --budget 5000000 --reservation 1000000
```

No API key belongs in source control or chat. `.state/`, environment files,
sessions, generated outputs, and dependencies are ignored by Git.

## Validation

```bash
.venv/bin/python scripts/check.py
cd agents/eve
npm run typecheck
npm test
npm run build
npm run test:runtime
```

Database tests use their own schemas. The managed acceptance harness launches and
restarts its own API, uses actual PostgreSQL and the pinned browser container,
and records explicit PASS/FAIL/BLOCKED outcomes. Live model testing is separate
and off by default. [Evaluation protocol](evals/protocol.json) defines the later
same-budget, repeated-run comparisons needed before superiority claims.

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
