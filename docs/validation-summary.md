# Validation summary

The final local gate run on 2026-11-07 passed on unchanged source. This is evidence
for the bounded implementation scope, not certification of a universal platform.

| Check | Observed result | Evidence |
|---|---|---|
| Python/platform suite | 148 tests and 18 subtests passed; zero failures, errors or skips | `evals/results/checks.json` |
| Real HTTP/PostgreSQL/Docker acceptance | All eight configured cases passed; three actual browser reports carry image identity | `evals/results/pytest-acceptance.json` |
| Original reference kernel | 25 tests passed | `evals/results/checks.json` |
| Agent adapter | 20 tests, typecheck, complete build, authenticated compiled-server smoke passed | `docs/agent-validation-update.json` |
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
times and a source-unchanged check. Its 166 JUnit cases include the 18 subtests;
they are not 166 independent product trials. Node checks and the restore drill
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

A genuine model-generated app and a separate controlled persistence repair now
passed all eight trusted checks and exported release manifests. Provider generation
receipts confirm the observed usage. Total key spend including adapter failures
was $0.05466171; the session authorization remains $5 and the unchanged $1 Gateway
budget is soft. The two earlier Gateway rejections were subsequently reconciled to zero using
their explicit pre-provider responses and matching settled usage. All failed attempts remain in
[live validation](live-validation.md).

This does not establish natural success rates, held-out performance, long-horizon
reliability or other domain capabilities. Independent visual review of the first
accepted app found low text contrast in delete buttons and completed tasks,
which the current eight-check suite does not measure. See
[live visual review](live-visual-review.json); this is a concrete coverage gap for
the next profile revision, not a complete accessibility sign-off.

See `implementation-roadmap.md` for deliverables and exit evidence, and
`production-readiness.md` for the current trust and deployment boundaries.

The newer repair-feedback and receipt changes were tested at source level. Earlier
dashboard, container-smoke and restore reports remain historical observations for
the revisions they identify; they are not silently rebound to this newer code.
