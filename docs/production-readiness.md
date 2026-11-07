# Production-readiness ledger

GraphOS implements a bounded, single-tenant platform and three offline
application profiles. It is not a universally capable or fully production-certified
agent platform. This ledger separates historical measurements from current
validation. The expanded mandatory suite and all 12 grader-calibration cases
passed. Two separate live pilots remain incomplete: the first dispatched three
trials and the second dispatched two; neither accepted a candidate. Their costs
were subsequently reconciled. The latest usage/output repair has 34 passing
adapter tests, typecheck and credential-free runtime smoke; its full platform
gate passed at `c5e4ff2`. The third cohort completed all six trials, accepted one
local-notes candidate and rejected five; all costs settled. Earlier
passing gates apply only to the source revisions they identify.

## Recorded evidence

| Area | Evidence | Scope |
|---|---|---|
| Durable orchestration | Real PostgreSQL fault/concurrency tests | Single controller service, transactional run locking |
| Recovery | API process restart, expired worker replacement | Local environment; no regional outage simulation |
| Local restore | [Measured PostgreSQL/CAS drill](restore-validation.json): identical table fingerprints, referenced object and release-manifest validation | Fresh retained scratch database on the same local cluster; no restored dispatch, remote backup or production RTO/RPO |
| Verification | [Full gate passed at `c5e4ff2`](../evals/results/checks.json): 245 Python tests plus 18 subtests, 25 reference tests and Ruff | Zero failures, errors or skips, source unchanged; gate completed in approximately 267 seconds; finite platform/fixture checks, not model reliability |
| Grader calibration | [12 of 12 expected outcomes observed](../evals/results/profile-calibration-20261107.json); actual historical artifact rejected by four new checks | Three conforming controls and nine specified defect injections; finite grader evidence, not model performance |
| Evidence binding | Wrong candidate, stale revision, incomplete report rejected | Exact input, suite, policy, image and artifact identities |
| Authorization | Builder cannot verify; reads require active scoped lease | Single tenant, shared credential per trusted service role |
| Budget accounting | Reservations, unknown-cost consumption, overrun incidents | Provider invoice limits require provider-side controls |
| External effects | Durable state, lost-token reconciliation, stale receipt rejection | Record/state machine tested; no real deployment/broker adapter |
| Model harness | Latest usage/output repair: 34 adapter tests, typecheck, credential-free runtime smoke and full platform gate passed | [Stream diagnosis](../evals/results/profile-pilot-interruption-20261107.json) and [failed-output accounting gap](../evals/results/profile-schema-rejection-reconciliation-20261107.json); passing tests do not establish live quality |
| Live evaluation | [Cohorts kept separate](profile-pilot-results.md): first 0/3 dispatched, second 0/2, third 1/6 | Third cohort completed all six with five failures and all costs settled; earlier cohorts retained with three/four undispatched; not a held-out success estimate |
| Current generated delivery | Third-cohort local-notes candidate passed, was [exported](../evals/results/profile-structured-pilot-deliveries-20261107.json), and received [desktop/mobile visual review](profile-visual-review.json) | No blocking visual defect observed in two populated/editing views; conditional focus styling observed; not full WCAG certification |
| Exploratory repair | [Task-list](../evals/results/repair-followup-static-web-20261107.json) and [inventory](../evals/results/repair-followup-local-inventory-20261107.json) each exhausted two attempts without acceptance | Task-list repair fixed ARIA/reflow but not focus width; inventory returned the identical candidate, rejected again. All costs known, no exports, excluded from first-attempt pilot denominator |
| Current CI | Both `c5e4ff2` workflows passed | [Run 42411292679](https://github.com/MichalKuderski/GraphOS/actions/runs/42411292679) and [run 42411288496](https://github.com/MichalKuderski/GraphOS/actions/runs/42411288496) |
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
| `static-web` v2 | Task-list behavior, persistence and the expanded accessibility gates | Fixture/regression/calibration passed; no current live pilot candidate accepted. Third cohort: strict output rejection/model-call limit, then focus contrast rejection |
| `local-notes` v1 | Create/edit/cancel/search/delete notes, input validation, literal user text and persistence | Fixture/regression/calibration passed; one third-cohort candidate accepted and exported, the other failed before verification with known usage; earlier failures retained |
| `local-inventory` v1 | Unique names, safe integer quantities, quantity updates, search/delete and persistence | Fixture/regression/calibration passed; no live pilot candidate accepted. Third cohort rejected long quantity-label overflow and text contrast |

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
grader changed. All 12 calibration cases produced their expected outcomes. The
actual historical candidate also failed populated/completed contrast, focus
outline width and mobile reflow under the new suite. Automated checks cover finite states and
rules, not full WCAG conformance. The focused-state outline gate can miss an
always-on outline; add a focused/unfocused negative control and fresh suite
binding before claiming that distinction is automatically verified. The accepted
notes artifact independently showed conditional focus CSS and a focused textbox
without that outline on unfocused controls, preserving that finite review result.
Screen-reader use, zoom, different browsers,
meaningful labels, interaction usability, and manual product review remain
separate requirements.

The [profile pilot](evaluation-pilot.md) separates fixture-based grader
calibration from serial real-model trials. Its contracts are disclosed, failures
remain in the denominator, and the [incomplete result](profile-pilot-results.md)
records every dispatched and undispatched trial. No candidate qualified for
export. The inventory interruption exposed a 60-second HTTP stream lease with
client reconnection disabled. The repair resumes only a GET stream for the same
delivery and cursor within the original deadline; it does not resend a model
request. Its tests, typecheck, fresh build and credential-free runtime smoke pass;
the full platform gate also passed at `801f711`. The
[interruption record](../evals/results/profile-pilot-interruption-20261107.json)
retains the diagnosis, both inventory receipts and subsequent operator-API
reconciliation to $0.024126. The run is `EXHAUSTED`, with no remaining reservation
or uncertain attempt; this accounting repair does not change its failed pilot
outcome. The second cohort then stopped after two trials: task-list reflow failed,
and notes output did not fulfill the runtime schema. Its known model charge was
initially lost at the broker error boundary, then reconciled from its receipt to
$0.008832. No uncertain costs remain from these cohorts.
The [refreshed receipts](../evals/results/profile-reconnect-pilot-receipts-20261107.json)
bring the cumulative provider-receipt sum to $0.14852750, matching key spend at
that observation. The $1 non-resetting soft budget remains unchanged.

The latest repair recovers complete usage only after confirmed session retirement
and validates it before forwarding failure accounting. The model is required to
use the runtime's exact typed reply tool. Build instructions now address the
observed roles, field validation, focus and wrapping defects. These changes have
34 passing adapter tests, typecheck, credential-free runtime smoke and the full
platform gate. The third cohort completed without source changes: one of six
accepted and five failed, with no undispatched trials or uncertain costs. The
[17 provider receipts](../evals/results/profile-structured-pilot-receipts-20261107.json)
total $0.13305905; cumulative receipt-backed spending before exploratory runs is
$0.28158655. A lower aggregate key-budget reading does not supersede that total.
The accepted notes release passed its finite independent desktop/mobile visual
spotcheck, with no observed horizontal overflow, overlap, clipped content or page
errors. Separate fresh task-list and inventory build/repair demonstrations each
exhausted two attempts without acceptance. The task-list repair corrected ARIA
and mobile failures but retained insufficient focus width. Inventory retained
populated Save-button contrast and long quantity/status text overflow on both
attempts. Neither run exported an artifact or changed the pilot result.
Their receipt costs were $0.03437364 and $0.03130749, respectively, bringing
cumulative receipt-backed session spending to **$0.34726768**. The
[final ledger/spend review](../evals/results/final-spend-ledger-review-20261107.json)
confirms zero reservations and uncertain attempts across all 13 dispatched runs.
The fresh key-budget aggregate is $0.34044667, lower by $0.00682101; its cause is
not established, so the higher receipt sum remains the conservative basis. This
is not invoice reconciliation. The $1 soft budget and $5 authorization remain unchanged.
Because
instructions were adjusted using observed failures, later results are development
evidence rather than untouched holdout performance. Even a completed
pilot cannot substitute for an untouched project-level test set,
matched-budget comparisons, or statistically justified reliability estimates.

## Required before wider production use

1. **Improve generation and precise repair within the existing contracts:** the
   completed pilot accepted one of six, and neither exploratory repair earned a
   release. Provide diagnostics that identify the failing control, computed
   style and state. Test provider-side `strict: true` with a minimal compatibility
   canary for the selected Gateway/model route before adopting it; forced tool
   selection alone did not guarantee schema-valid arguments. Keep current
   acceptance thresholds and failed trials intact. Detect no-op model repairs
   before redundant verification when candidate/input/suite/policy identities
   match. New experiments need their
   own declared source and denominator.
2. **Close specific grader and recovery gaps:** add focused/unfocused negative
   controls so always-on outlines cannot satisfy a state-change claim; bind
   revised suites to fresh evidence. Persist Gateway generation IDs and failed-call
   receipt identities before a worker's final report reaches the ledger. Existing
   terminal usage recovery does not close the earlier crash window. Continue
   manual accessibility and product review beyond the finite notes spotcheck.
3. **Representative evaluation:** versioned held-out project families,
   matched-budget single-agent and multi-agent comparisons, repeated runs,
   uncertainty intervals, escaped-defect measurement and human product review.
   Predeclare promotion criteria and do not tune against the held-out set.
4. **Failure handling and long-horizon operation:** workload-appropriate load/soak
   tests, explicit provider/worker outages, bounded retry storms, deployment
   upgrades with paused work, disk exhaustion, and safe recovery without duplicate
   model spending or external actions.
5. **Identity and isolation:** external identity/SSO when needed, tenant-scoped
   authorization tested against cross-tenant access, short-lived worker authority,
   credential rotation/revocation, dedicated sandbox hosts or microVMs, and
   independent security assessment before arbitrary hostile workloads. Adding a
   tenant field does not establish multi-tenant isolation.
6. **Operations:** encrypted backups and verified restore objectives, monitoring,
   paging, deployment/rollback procedures, data retention, dependency maintenance,
   resource quotas, availability targets and incident ownership.
7. **Real action adapters:** receiver-enforced deduplication, authoritative
   reconciliation, credential scoping, explicit compensation, and provider-specific
   tests before deployments, messages, payments, or trading actions are enabled.
8. **Domain implementation:** only after the applicable evaluation, isolation and
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
