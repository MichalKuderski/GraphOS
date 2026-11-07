# Production-readiness ledger

GraphOS is an implemented first milestone, not a universally capable or fully
production-certified agent platform. This ledger prevents a successful fixture
test from being promoted into an unsupported capability claim.

## Implemented and exercised

| Area | Evidence | Scope |
|---|---|---|
| Durable orchestration | Real PostgreSQL fault/concurrency tests | Single controller service, transactional run locking |
| Recovery | API process restart, expired worker replacement | Local environment; no regional outage simulation |
| Local restore | [Measured PostgreSQL/CAS drill](restore-validation.json): identical table fingerprints, referenced object and release-manifest validation | Fresh retained scratch database on the same local cluster; no restored dispatch, remote backup or production RTO/RPO |
| Verification | Actual Docker/Chromium journeys | Fixed task-list web-app profile only |
| Evidence binding | Wrong candidate, stale revision, incomplete report rejected | Exact input, suite, policy, image and artifact identities |
| Authorization | Builder cannot verify; reads require active scoped lease | Single tenant, shared credential per trusted service role |
| Budget accounting | Reservations, unknown-cost consumption, overrun incidents | Provider invoice limits require provider-side controls |
| External effects | Durable state, lost-token reconciliation, stale receipt rejection | Record/state machine tested; no real deployment/broker adapter |
| Model harness | eve build, types, unit tests, authenticated server smoke; real Gateway attempt retained | Real model build and controlled repair passed the fixed suite |
| Targeted repair | PostgreSQL lease, stale-evidence and worker tests | Latest rejected candidate plus bounded diagnostics; every repair needs fresh verification |
| Operator UI | Browser UI actions and responsive behavior | Control plane; candidate HTML is never embedded here |

Machine-readable results are in `evals/results/`. Test counts refer to finite
tests and must not be represented as a probability of correctness or uptime.
The explicit restore run is recorded separately in `docs/restore-validation.json`;
its previous infrastructure failure is retained in
`docs/restore-infrastructure-failure.json`. See [the drill procedure](restore-drill.md)
for capture boundaries and exclusions.

## Current release boundary

The active HTTP profile accepts one registered task-list objective and its exact
behavioral requirements. Arbitrary objectives and additional criteria are
rejected, because the existing suite cannot certify them. The general ledger's
DAG scheduling is tested separately; the public profile does not yet expose
multi-module application integration.

The deterministic fixture path uses real storage, HTTP workers, and browser
verification. Its provenance says fixture. It is not an AI-generated project,
and it is never a silent fallback for an unavailable model.

Failed candidates can be replaced within bounded attempt limits. A retry receives
the latest rejected candidate and bounded verifier diagnostics only for the same
revision, input, suite and policy. Artifact reads require its current build lease.
Diagnostics are untrusted context, not acceptance evidence; the replacement must
pass a new independent verification. One controlled persistence repair has passed; natural repair success rates remain unmeasured.

The dedicated credential and billing verification now permit live generation.
GPT-6 Luna was unavailable on the team's free tier; the explicit replacement,
GPT-5.1 Codex Mini, completed a genuine build and one controlled repair. Both
passed eight independent checks and exported evidence-bound releases. Total
provider-reported spend including failed attempts was $0.05466171; the unchanged
$1 Gateway budget is a soft cap, with $5 total session authorization. The two earlier
Gateway rejections were reconciled to zero from their pre-provider rejection
responses and matching settled usage; their failed attempt records remain. See [live validation](live-validation.md) for all attempts,
receipts, adapter fixes and limitations. These observations do not establish a
model success rate, broad production readiness, or superiority over a baseline.

The initial app's separate visual review found low text contrast that the current
eight-check suite misses. This concrete grader gap remains open; passing release
evidence certifies only the declared checks, not complete accessibility.

## Required before wider production use

1. **Extend live evidence:** the initial fixed-contract build and controlled repair
   have passed. Preserve all failed attempts; expand to representative tasks and
   repeat trials before estimating reliability.
2. **Representative evaluation:** versioned held-out task families, matched-budget
   single-agent and multi-agent comparisons, repeated runs, uncertainty intervals,
   escaped-defect measurement and human product review.
3. **Domain implementation:** build actual tools and graders for games, bots,
   data, media and trading research. Current profiles are blocked contracts.
4. **Long-horizon operation:** workload-appropriate load/soak tests, deployment
   upgrades with paused work, provider outages, disk exhaustion and retry storms.
5. **Identity and isolation:** external identity/SSO when needed, tenant-scoped
   authorization, credential rotation, dedicated sandbox hosts or microVMs, and
   independent security assessment before arbitrary hostile workloads.
6. **Operations:** encrypted backups and verified restore objectives, monitoring,
   paging, deployment/rollback procedures, data retention, dependency maintenance,
   resource quotas, availability targets and incident ownership.
7. **Real action adapters:** receiver-enforced deduplication, authoritative
   reconciliation, credential scoping, explicit compensation, and provider-specific
   tests before deployments, messages, payments, or trading actions are enabled.

## Trust and limitation details

- The API is single-tenant. Operators can inspect the tenant's artifacts;
  builders/verifiers require a current task lease and a permitted artifact digest.
- Verifier credentials belong to a trusted service. A correctly shaped report is
  not remote hardware attestation. Do not give that credential to generated code.
- Docker shares the host kernel. Chromium's internal process sandbox is disabled
  in the constrained container; this fact is included in policy/evidence. No
  network, credentials, writable root, capabilities, or Docker socket are exposed
  to generated applications. This is not proof against browser/kernel escapes.
- Original role tokens are not stored in browser storage. They require rotation
  through private configuration and service restart; full credential lifecycle
  management and tenant identity provisioning are not implemented.
- Registered suite/policy changes block further work and release until revision.
  The first revision strategy invalidates the entire run conservatively. Selective
  semantic invalidation is a later optimization requiring its own evaluation.
- Trusted clock and database/storage integrity are assumptions. Local hashes detect
  tampering but cannot defend against an attacker controlling the entire host.
- Outbox events commit atomically with ledger state. External notification delivery
  and dead-letter operations are not yet implemented.
- Runtime assets are supplied by the source tree or `GRAPHOS_RUNTIME_ROOT`.
  Standalone Python wheel installation requires those explicit trusted assets;
  the supplied container sets the root correctly.

No finite validation can establish 100% accuracy or reliability over all future
inputs, models, dependencies, and timeframes. Promotion must follow evidence for
the actual operating scope.
