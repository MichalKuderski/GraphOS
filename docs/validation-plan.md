# GraphOS validation plan

The implemented acceptance suite tests the composed static-web vertical slice:
real HTTP authorization, PostgreSQL transitions, workers, immutable bundles, and
the trusted Docker/browser verifier. A deterministic fixture is identified as
`fixture` in both run provenance and results. Passing these checks does not measure
model capability or establish production readiness.

## Run it

Configure the distinct operator, builder, and verifier bearer tokens,
`GRAPHOS_DATABASE_URL`, `GRAPHOS_ARTIFACT_ROOT`, and the pinned
`GRAPHOS_VERIFIER_IMAGE_DIGEST` through the documented private
environment. The local runner can read `.state/local.env`; it never writes secret
values to its public result file. Build the trusted verifier image first.

```sh
python -m scripts.acceptance --managed --output evals/results/acceptance.json
python -m pytest -q tests/test_acceptance.py
```

`--managed` launches a real API subprocess and restarts it against the same
database and artifact store. External API mode is supported with `--api-url`; its
restart check is explicitly `NOT_RUN`. Missing test configuration makes pytest
skip, not pass. Docker or database failures with a configured environment fail
the acceptance run. Results retain case outcomes and actual verification reports.
Never count a skipped or unavailable test as successful evidence.

The crash case launches a disposable worker process that claims work over HTTP
and exits with code 137 immediately after receiving its lease. The suite waits
for the PostgreSQL-authoritative lease to expire, checks that uncertain spend
pauses dispatch, and reconciles the fixture's known zero cost before claiming a
replacement. Zero is known because that injected process exits before any
builder, model, or other tool executes. It then checks fencing and duplicate
receipt handling. It does not simulate
a database crash or claim complete distributed fault coverage.

## What must pass

| Check | Evidence |
| --- | --- |
| Fixture worker to release | Actual builder and verifier worker calls, real browser report, current release bindings |
| Admission/submission retries | Same admission returns the same run; conflicting reuse rejected; duplicate submission does not charge again |
| Capability boundary | Unsupported task objectives and requirements cannot be certified by the fixed task-list suite |
| Role separation/cancellation | Builder token cannot claim verifier work; cancelled run blocks new work and old completion |
| Artifact/evidence binding | Actual browser report cannot certify an altered candidate hash; incomplete passed certificates are rejected; revised specification invalidates accepted evidence and old receipts |
| Negative candidate | Valid bundle with broken behavior fails the real trusted browser checks and cannot release |
| Worker crash | Real process exits after claim; uncertain spend blocks dispatch until authoritative fixture reconciliation; replacement fences old receipt |
| Controller restart | New API process reads unchanged accepted task, events, budget, bundle, evidence, and release bindings |

Reports and fixtures must not contain service secrets. The accepted artifact is
an exact content digest, not a mutable working directory. Receipt retries may
return the original result or a conflict, but cannot mint fresh evidence or
charge twice. No helper fabricates a passing browser report.

## Live model execution

`--live` additionally requests a real `eve` builder attempt when gateway auth is
configured. Missing auth is recorded as `BLOCKED`; fixture generation never
substitutes for a model failure. A single live result is an observed attempt,
not an accuracy estimate. Its actual generated artifact still runs through the
same trusted verifier. Model-quality comparison remains `PLANNED_NOT_MEASURED`
until repeated, controlled trials exist.

## Comparison protocol

The machine-readable plan is `evals/protocol.json`. Begin with 30 private tasks
and five independent trials per task as a diagnostic pilot. Split by project or
repository into development, validation, and untouched release sets. Hold task
scope, aggregate spend, elapsed-time limits, compute and network conditions
constant; interleave configurations across time. Include planning, failed
branches, judging and repair in cost. Compare a single capable agent, a builder
plus verifier, a fixed graph, and adaptive routing.

Report completion, cost per verified result, latency, repeatability (`pass^k`),
escaped defects, intervention and recovery. `pass@k` means at least one success;
`pass^k` means all trials succeed. Do not raise aggregate success to the kth
power or treat dependent assertions as independent samples. Use paired,
project-clustered uncertainty. Select a superiority or noninferiority criterion
before inspecting held-out results; an inconclusive pilot requires more data.

Before broader deployment, add concurrent API admission and dispatch stress,
database interruption/recovery, storage corruption, real adapter reconciliation,
backup restoration, model-provider outages, and varied adversarial browser
candidates. Each remains unproved by the current vertical slice unless separate
measured results explicitly cover it.

The separate [local PostgreSQL/CAS restore drill](restore-drill.md) now has a
[passing measured result](restore-validation.json). It covers a fresh scratch
restore on the same cluster and referenced-object integrity; production backup,
encryption, remote outage and safe dispatch resumption remain outside that result.
