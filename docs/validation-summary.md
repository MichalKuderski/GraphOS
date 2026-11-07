# Validation summary

The final local gate run on 2026-11-07 passed on unchanged source. This is evidence
for the bounded implementation scope, not certification of a universal platform.

| Check | Observed result | Evidence |
|---|---|---|
| Python/platform suite | 138 tests and 18 subtests passed; zero failures, errors or skips | `evals/results/checks.json` |
| Real HTTP/PostgreSQL/Docker acceptance | All eight configured cases passed; three actual browser reports carry image identity | `evals/results/pytest-acceptance.json` |
| Original reference kernel | 25 tests passed | `evals/results/checks.json` |
| Agent adapter | 16 tests, typecheck, complete build, authenticated compiled-server smoke passed | `docs/agent-validation-update.json` |
| Dashboard | Actual-backend creation, revision, cancellation, release download, responsive layout and credential checks | `docs/dashboard-validation.json` and screenshots |
| CLI delivery | Current release manifest and candidate hashes verified; atomic export completed | `docs/cli-validation.json` |
| Packaged API | 18 non-root/read-only service checks passed; exact tested image/source identities recorded | `docs/container-validation.json` |
| Local restore | Ten tables restored; 18 CAS objects and four release manifests verified; row/schema identities match | `docs/restore-validation.json` |

The packaged API report explicitly identifies CLI/worker/transport changes made
after that image build. The final source suite covers those changes. GitHub's
workflow builds the API from each submitted revision; its live result belongs
to the corresponding commit and should be checked on the pull request.

`checks.json` records a SHA-256 identity over the tested Python/runtime assets,
profiles, verifier, tests, scripts, eve source/instructions and dependency declarations, plus start/end
times and a source-unchanged check. Its 156 JUnit cases include the 18 subtests;
they are not 156 independent product trials. Node checks and the restore drill
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

One real Gateway request was attempted and rejected with HTTP403
`customer_verification_required`; no model artifact was generated. Gateway reported
$0 spend, while the ledger retained a $1 uncertain reservation. The failed attempt
and provider observation are preserved in [live validation](live-validation.md).
The observed accepted applications remain explicit deterministic fixtures. Successful live generation,
provider usage/cancellation, model success rates, matched-budget comparisons,
long-horizon service reliability, and the other domain profiles remain unverified.
The authorized implementation-session model budget remains $5; the credential authenticates and a $1 soft budget is verified. Vercel team payment
verification and accounting review now block the next live attempt.

See `implementation-roadmap.md` for deliverables and exit evidence, and
`production-readiness.md` for the current trust and deployment boundaries.

The newer repair-feedback and receipt changes were tested at source level. Earlier
dashboard, container-smoke and restore reports remain historical observations for
the revisions they identify; they are not silently rebound to this newer code.
