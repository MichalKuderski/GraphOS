# Validation summary

The final local gate run on 2026-11-07 passed on unchanged source. This is evidence
for the bounded implementation scope, not certification of a universal platform.

| Check | Observed result | Evidence |
|---|---|---|
| Python/platform suite | 119 tests and 14 subtests passed; zero failures, errors or skips | `evals/results/checks.json` |
| Real HTTP/PostgreSQL/Docker acceptance | All eight configured cases passed; three actual browser reports carry image identity | `evals/results/pytest-acceptance.json` |
| Original reference kernel | 25 tests passed | `evals/results/checks.json` |
| Agent adapter | 11 tests, typecheck, complete build, authenticated compiled-server smoke passed | `docs/agent-validation.json` |
| Dashboard | Actual-backend creation, revision, cancellation, release download, responsive layout and credential checks | `docs/dashboard-validation.json` and screenshots |
| CLI delivery | Current release manifest and candidate hashes verified; atomic export completed | `docs/cli-validation.json` |
| Packaged API | 18 non-root/read-only service checks passed; exact tested image/source identities recorded | `docs/container-validation.json` |
| Local restore | Ten tables restored; 18 CAS objects and four release manifests verified; row/schema identities match | `docs/restore-validation.json` |

The packaged API report explicitly identifies CLI/worker/transport changes made
after that image build. The final source suite covers those changes. GitHub's
workflow builds the API from each submitted revision; its live result belongs
to the corresponding commit and should be checked on the pull request.

`checks.json` records a SHA-256 identity over the tested Python/runtime assets,
profiles, verifier, tests, scripts and dependency declarations, plus start/end
times and a source-unchanged check. Its 133 JUnit cases include the 14 subtests;
they are not 133 independent product trials. Node checks and the restore drill
are separately scoped evidence, not additional model-success observations.

## Failed infrastructure runs remain visible

The initial missing-image-configuration result and later disk-exhaustion results
are retained in `evals/results/`. Docker's VFS driver created full init and
writable copies; failed container creation left unreferenced copies that ordinary
cache pruning did not reclaim. No affected run received successful acceptance.

Targeted, approved cleanup removed contents of eight proven task-created orphan
copies after checking Docker references and matching the trusted verifier hash.
The database and current verifier were preserved. `docs/storage-recovery.json`
records the recovery. The final complete suite then passed; this is not a claim
that GraphOS automatically repairs host storage or implements disk admission.

## What remains unmeasured

No paid model generation occurred. The observed accepted applications are
explicit deterministic fixtures, with zero model charges. Live generation,
provider usage/cancellation, model success rates, matched-budget comparisons,
long-horizon service reliability, and the other domain profiles remain unverified.
The authorized implementation-session model budget remains $5; credentials and
verified provider-side spending controls are still required before live calls.

See `implementation-roadmap.md` for deliverables and exit evidence, and
`production-readiness.md` for the current trust and deployment boundaries.
