# Production-readiness ledger

GraphOS implements a bounded, single-tenant platform and three offline
application profiles. It is not a universally capable or fully production-certified
agent platform. This ledger separates historical measurements from the current
source's implemented scope. No new expanded-suite or pilot pass is asserted
until its version-bound result is recorded.

## Recorded evidence

| Area | Evidence | Scope |
|---|---|---|
| Durable orchestration | Real PostgreSQL fault/concurrency tests | Single controller service, transactional run locking |
| Recovery | API process restart, expired worker replacement | Local environment; no regional outage simulation |
| Local restore | [Measured PostgreSQL/CAS drill](restore-validation.json): identical table fingerprints, referenced object and release-manifest validation | Fresh retained scratch database on the same local cluster; no restored dispatch, remote backup or production RTO/RPO |
| Verification | Historical Docker/Chromium journeys and live release manifests | Earlier fixed task-list revision; expanded profile evidence pending |
| Evidence binding | Wrong candidate, stale revision, incomplete report rejected | Exact input, suite, policy, image and artifact identities |
| Authorization | Builder cannot verify; reads require active scoped lease | Single tenant, shared credential per trusted service role |
| Budget accounting | Reservations, unknown-cost consumption, overrun incidents | Provider invoice limits require provider-side controls |
| External effects | Durable state, lost-token reconciliation, stale receipt rejection | Record/state machine tested; no real deployment/broker adapter |
| Model harness | eve build, types, unit tests, authenticated server smoke; actual model runs and failed attempts retained | Real model build and controlled repair passed the earlier eight-check task-list suite |
| Targeted repair | PostgreSQL lease, stale-evidence and worker tests | Latest rejected candidate plus bounded diagnostics; every repair needs fresh verification |
| Operator UI | Browser UI actions and responsive behavior | Control plane; candidate HTML is never embedded here |

Machine-readable results are in `evals/results/`. Test counts refer to finite
tests and must not be represented as a probability of correctness or uptime.
The explicit restore run is recorded separately in `docs/restore-validation.json`;
its previous infrastructure failure is retained in
`docs/restore-infrastructure-failure.json`. See [the drill procedure](restore-drill.md)
for capture boundaries and exclusions. Each result applies to the source,
profile, suite, policy and verifier image it identifies. Earlier dashboard,
packaging, restore and model observations are not silently promoted to cover
later code or broader contracts.

## Current release boundary

The current HTTP profile registry implements three fixed offline contracts:

| Profile | Scope | Current evidence boundary |
|---|---|---|
| `static-web` v2 | Task-list behavior, persistence and the expanded accessibility gates | New-suite validation and live results pending; historical v1 passes remain v1 evidence |
| `local-notes` v1 | Create/edit/cancel/search/delete notes, input validation, literal user text and persistence | Implemented; new-suite and live results pending |
| `local-inventory` v1 | Unique names, safe integer quantities, quantity updates, search/delete and persistence | Implemented; new-suite and live results pending |

Every application consists of three offline files. None implements a backend,
authentication, cross-device synchronization, a backup service, or multi-user
storage. Local inventory does not certify accounting or purchasing; local notes
does not provide secure document storage. Browser localStorage can be cleared or
unavailable and is unsuitable as the sole copy of important information.

Arbitrary objectives and additional criteria are rejected because no grader
certifies them. The ledger's DAG scheduling is tested separately; these profiles
do not yet expose multi-module application integration or parallel developer
agents composing a complete product.

The trusted verifier now hashes and copies its complete asset tree read-only,
including axe-core 4.14.0. Profile, verifier-asset and image changes alter the
evidence binding and require current verification. The new suites require zero
axe violations and zero incomplete findings in empty and populated states; the
task list also checks completed tasks. Keyboard operation and reachability,
visible focus, and mobile reflow at 320 and 390 CSS pixels are explicit gates.
An incomplete automated finding is not silently treated as a pass.

The deterministic fixture path uses real storage, HTTP workers, and browser
verification. Its provenance says fixture. It is not an AI-generated project,
and it is never a silent fallback for an unavailable model.

Failed candidates can be replaced within bounded attempt limits. A retry receives
the latest rejected candidate and bounded verifier diagnostics only for the same
revision, input, suite and policy. Artifact reads require its current build lease.
Diagnostics are untrusted context, not acceptance evidence; the replacement must
pass a new independent verification. One controlled persistence repair has passed; natural repair success rates remain unmeasured.

The historical live milestone used a dedicated credential after billing
verification. GPT-6 Luna was unavailable on the team's free tier; the explicit
replacement, GPT-5.1 Codex Mini, completed a genuine build and one controlled
repair of the earlier task-list revision. Both passed its eight independent
checks and exported evidence-bound releases. At that milestone's recorded
observation, provider-reported spend including failed attempts was $0.05466171;
this is not a live balance or an allowance for a later batch. The $1 Gateway
budget is a soft cap, with $5 total session authorization. The two earlier
Gateway rejections were reconciled to zero from their pre-provider rejection
responses and matching settled usage; their failed attempt records remain. See [live validation](live-validation.md) for all attempts,
receipts, adapter fixes and limitations. These observations do not establish a
model success rate, broad production readiness, or superiority over a baseline.

The initial app's separate visual review found low text contrast that its
eight-check suite missed. That observed defect motivated the new accessibility
gates; it does not disappear from the historical release merely because the
grader changed. Calibration must show that the new gates reject this class of
defect and accept conforming controls. Automated checks cover finite states and
rules, not full WCAG conformance. Screen-reader use, zoom, different browsers,
meaningful labels, interaction usability, and manual product review remain
separate requirements.

The [profile pilot](evaluation-pilot.md) separates fixture-based grader
calibration from serial real-model trials. Its contracts are disclosed, failures
remain in the denominator, and no result is claimed before execution. Even a
completed pilot cannot substitute for an untouched project-level test set,
matched-budget comparisons, or statistically justified reliability estimates.

## Required before wider production use

1. **Calibrate and exercise the current contracts:** validate correct fixtures and
   deliberately defective examples for all three profiles, run bounded live
   trials on the current suites, and retain failures and costs. Exercise current
   repair paths without reusing stale evidence. Add manual accessibility and
   product review before calling a result suitable for its users.
2. **Representative evaluation:** versioned held-out project families,
   matched-budget single-agent and multi-agent comparisons, repeated runs,
   uncertainty intervals, escaped-defect measurement and human product review.
   Predeclare promotion criteria and do not tune against the held-out set.
3. **Failure handling and long-horizon operation:** workload-appropriate load/soak
   tests, explicit provider/worker outages, bounded retry storms, deployment
   upgrades with paused work, disk exhaustion, and safe recovery without duplicate
   model spending or external actions.
4. **Identity and isolation:** external identity/SSO when needed, tenant-scoped
   authorization tested against cross-tenant access, short-lived worker authority,
   credential rotation/revocation, dedicated sandbox hosts or microVMs, and
   independent security assessment before arbitrary hostile workloads. Adding a
   tenant field does not establish multi-tenant isolation.
5. **Operations:** encrypted backups and verified restore objectives, monitoring,
   paging, deployment/rollback procedures, data retention, dependency maintenance,
   resource quotas, availability targets and incident ownership.
6. **Real action adapters:** receiver-enforced deduplication, authoritative
   reconciliation, credential scoping, explicit compensation, and provider-specific
   tests before deployments, messages, payments, or trading actions are enabled.
7. **Domain implementation:** only after the applicable evaluation, isolation and
   operating gates, add actual tools and graders for games, bots, data, media and
   trading research. Their current profiles remain blocked contracts. For trading,
   software correctness, statistical validity, execution reliability and evidence
   of an investable strategy require separate evaluation; no live trading is enabled.

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
