# GraphOS implementation roadmap

GraphOS currently implements an evidence-controlled, single-tenant execution
slice for one registered task-list application. The PostgreSQL ledger supports
task dependencies, but the public profile deliberately admits one fixed product
contract. Fixture generation, model integration, a parallel development team,
and a measured advantage over other systems are different milestones.

This roadmap defines deliverables and promotion evidence, not calendar promises.
The current evidence and its limits remain in `production-readiness.md`,
`validation-plan.md`, and the versioned files under `evals/results/`. Never replace
those measurements with a roadmap target or a count of planned features.

## Dependency order

1. Freeze the current reproducible baseline and complete a real model slice.
2. Add a small family of supported product contracts and trusted graders.
3. Compose actual parallel agent work into one verified application.
4. Compare configurations on untouched, representative tasks before promoting
   adaptive routing or claiming a reliability/efficiency improvement.
5. Complete identity, isolation, recovery, and operating controls before exposing
   the enlarged execution surface to untrusted users or consequential actions.
6. Add domain profiles individually, with separate evidence and release gates.

Identity and operations work can start immediately. Broader model capabilities
do not remove those dependencies. A production operator must be able to disable
a profile or model configuration while preserving its run history and receipts.

## Phase 0 — Reproducible baseline and actual model generation

**Deliverable:** A tagged source revision, exact dependency locks, immutable
verifier image, documented configuration, and one genuine model-generated
task-list artifact with current browser evidence. Run the existing fixture suite
as integration evidence alongside the live attempt. Record provider/model
identity, request and usage identifiers, local reservation, actual charge,
failure/repair history, artifact digest, and acceptance outcome.

**Dependencies:** Dedicated model credential, authenticated eve service, verified
provider-side spending control, and an explicitly authorized total budget. The
existing session authorization must not be increased by a retry, a benchmark,
or an implied "production" milestone. Missing credentials or spending controls
remain explicit blockers; no fixture fallback is permitted.

**Exit evidence:** Reproduction commands work from a clean checkout; mandatory
platform gates execute without skips; a real candidate is verified or its
failure is retained with its incurred cost. Only a passing live candidate closes
the successful-generation gate. A single passing result establishes that
observed capability once, not a success rate. At least one controlled repair
exercise must demonstrate that repairs preserve provenance and cannot reuse
stale evidence or exceed the authorized attempt/spend boundary.

## Phase 1 — Widen contracts before widening promises

**Deliverable:** Two or three narrowly defined application families with explicit
schemas for their inputs, supported options, outputs, required capabilities,
resource ceilings, and acceptance criteria. Implement a contract compiler that
maps supported user requirements to versioned task and verification contracts.
Unrecognized requirements remain unresolved or are rejected; they cannot be
silently discarded while returning a passing certificate.

For example, progress from the fixed task list to a local notes app and a small
inventory app before enabling arbitrary full-stack development. Each family
needs known-correct examples, deliberately defective examples, browser journeys,
data/state checks, and a declared boundary for subjective product judgment.
Adding a backend also requires a real isolated service/data environment and
grader; a static screenshot or mocked endpoint does not establish that capability.

**Dependencies:** Phase 0, a trusted profile registry, compatibility rules for
suite/policy changes, and resource-isolated test execution. The builder may
propose tests, but cannot amend the mandatory grader or its release threshold.

**Exit evidence:** Every admitted requirement has a matching acceptance check
or an explicitly identified human review obligation. Positive and defective
reference artifacts establish that graders can accept correct behavior and
reject material failures. New suites run on clean candidate environments;
unsupported objectives and additional criteria still fail admission. Prior
profiles continue passing their regression suite after the extension.

## Phase 2 — A real parallel development graph

**Deliverable:** A planner that emits typed, versioned task proposals, a bounded
scheduler, isolated workspaces, interface contracts, a serialized integration
queue, and a final integration verifier. Start with a small graph: independent
UI and domain-logic workers consume the same approved interface contract, then
an integrator assembles their artifacts and an independent verifier exercises
the complete application. Add concurrency because work can be separated, not
because a target agent count sounds impressive.

Agent messages should identify run/revision, task/attempt, parent artifact
digests, assumptions, proposed decisions, artifact references, and outstanding
questions. Durable artifacts and ledger events carry the shared state. Freeform
chat is useful context but cannot authorize a transition. Agents receive only
the task material and capabilities they need; a verifier does not inherit a
builder's endorsement as evidence.

Use one owner for durable dispatch and recovery. Reconcile eve sessions and
tool execution with the PostgreSQL attempt identity rather than introducing a
second independent retry authority. Allocate ownership for overlapping files,
API schemas, migrations and dependency locks. Conflicting patches enter the
integration queue; they must not overwrite each other by arrival time.

**Dependencies:** Phase 1 contracts; scoped identities and isolated execution
for the new tools; versioned interface schemas; deterministic artifact assembly.
The existing ledger concurrency tests are a foundation, not proof that complete
applications compose correctly.

**Exit evidence:** Two workers actually run concurrently and produce separate
artifacts; the assembled app passes its independent integration contract.
Inject an incompatible interface, stale upstream artifact, worker crash, duplicate
receipt, and integration failure. Each must reject or repair the affected work
without publishing a mixed-version release. A spec update fences stale builders
and verifiers. Measure total cost and elapsed time against a single-worker run
with the same product contract. Label fixture and model runs separately.

Keep full-run invalidation initially. Selective invalidation is a later
optimization: it needs explicit dependency semantics and tests showing that
affected evidence is always removed. A graph reachability algorithm alone does
not establish that every semantic dependency was represented.

## Phase 3 — Held-out evaluation and measured routing

**Deliverable:** Versioned private task packs, an isolated grading service,
repeated-run orchestration, paired analysis, and an inspectable evaluation report.
Create projects with meaningful variation in requirements, coupling, ambiguity,
and duration. Thirty paraphrases of the current task-list prompt are not thirty
independent product families.

Split by project/repository into development, validation, and untouched release
sets. Keep hidden tests out of builder access while disclosing the behavior
they enforce. Audit grader false rejection, missed defects and candidate attempts
to interfere with the test harness. Preserve failed and infrastructure-limited
runs under a predefined scoring policy; do not selectively rerun losses.

Compare a capable single agent, a builder plus verifier, a fixed parallel graph,
and adaptive routing using the same task scope and aggregate budgets. Include
planning, model calls, failed branches, verification, repairs, infrastructure,
and human intervention. Pin versions and resource limits; interleave runs to
reduce time-of-day/provider confounding. Add separate robustness strata for
timeouts, rate limits, context resets and long dependency chains.

**Dependencies:** Phases 0–2, actual authorized evaluation budget, independent
task curation, and stable telemetry. The initial 30-task/five-trial plan in
`evals/protocol.json` is a diagnostic pilot, not a sample-size justification for
very high reliability claims.

**Exit evidence:** Paired task/project-clustered intervals for verified completion,
cost per accepted result, latency, repeatability, intervention and escaped
defects. Predeclare a superiority or noninferiority decision before the release
set is opened. Promote a router only on held-out evidence; an inconclusive
result remains inconclusive. Report per-family failures rather than hiding a
weak family inside a global average. Re-evaluate after model, tool, prompt,
memory, or suite changes that could alter the result.

Learned memory and routing enter through this gate. Memory entries need source,
scope, version, freshness and invalidation rules. Compare against no-memory and
fixed-routing baselines. A different reviewer model may reduce common failures,
but statistical independence must be measured rather than assumed.

## Phase 4 — Identity and execution isolation

**Deliverable:** Per-service/per-worker identities, short-lived task-scoped
credentials, rotation/revocation, tenant and artifact authorization, and a written
threat model. If the product remains single tenant, retain that explicit scope;
do not add a tenant field and call the system multi-tenant.

Move generated application execution onto dedicated executor hosts or stronger
isolation such as microVMs according to the workload. Review the currently
disabled Chromium process sandbox and shared-kernel Docker boundary before
accepting hostile public workloads. Keep candidate code away from broker,
database, model, verifier and release credentials. Control network access at the
execution boundary; dependency downloads, outbound tools and deployment APIs
need distinct, bounded capabilities. Record executor/image/policy identity in
evidence and retain reproducible build manifests.

**Dependencies:** Required before expanding to arbitrary code, tenant data, or
consequential tools; can proceed in parallel with Phases 1–3.

**Exit evidence:** Cross-tenant and cross-task access tests, expired/revoked-token
tests, credential rotation without implicit privilege persistence, bounded
resource exhaustion tests, egress enforcement, and an independent security
review appropriate to the deployment. Successful finite tests are evidence for
the stated boundary, not a claim that sandbox escapes are impossible.

## Phase 5 — Recovery and operations

**Deliverable:** Coherent encrypted database/artifact backups, isolated restore
procedures, monitoring, actionable alerts, defined owners, retention and garbage
collection rules, migration/rollback playbooks, and workload-specific operating
objectives. Implement actual outbox delivery with deduplication and dead-letter
handling before claiming notifications are durably delivered.

The local restore drill uses a read-only exported database snapshot, copies
the content-addressed objects referenced by that snapshot, restores into a fresh
scratch database, and verifies row/artifact/release identities. It must never use
`--clean`, replace a live database, or purge the source artifact store. Preserve
unknown external effects, unsettled spend, idempotency keys and receipts.

That narrow local drill is now implemented and has a
[recorded passing run](restore-validation.json), with its exact coverage and
exclusions in [the procedure](restore-drill.md). The remaining exit work concerns
the actual production backup, encryption, recovery environment and safe resume
process; the local result does not close those gates.

**Dependencies:** Stable schema and artifact retention; a backup key/access
policy; storage capacity; explicit production RPO/RTO and incident ownership.
Before resuming dispatch after a real restoration, revoke old execution
credentials, fence surviving workers across recovery generations, and reconcile
external actions and provider charges. Restoring an old database does not undo
effects that occurred after its snapshot.

Unknown build costs also require reconciliation before replacement dispatch.
Conservatively charging a reservation is an accounting estimate, not evidence
that an interrupted provider request has stopped spending. Retain the pause
across run revisions until every uncertain attempt has a trustworthy receipt.

**Exit evidence:** A clean-room restore of database and referenced artifacts,
verified manifests and evidence, and a measured local restore duration. Then
separately test the actual deployment's backup schedule, encryption/key recovery,
remote storage, outage modes, upgrade with paused work, disk exhaustion, and
retry storms. A local scratch restore closes only that narrow recoverability
gap; it does not establish point-in-time recovery, high availability, a regional
RTO/RPO, or safe automatic resumption of external actions.

## Phase 6 — Domain profiles and real action adapters

Promote each profile independently. Reuse the orchestration contracts while
adding the tools, resources, graders and review obligations the domain requires.

| Profile | First bounded deliverable | Required promotion evidence |
| --- | --- | --- |
| Full-stack apps | One supported service/database stack with migrations | End-to-end stateful journeys, authorization, clean install, migration/rollback, declared load and resource limits |
| Bots | One platform and a limited tool catalog | Real sandbox callbacks, duplicate/out-of-order events, rate limits, scoped credentials, user-visible message correctness |
| Games | One engine and a small playable genre | Seeded simulation tests where applicable, save/load, reachability, input and frame-time budgets on declared hardware, human playtesting |
| Data projects | Reproducible transformations and analysis on versioned inputs | Grain/schema/quality checks, leakage and numerical validation, reproducible outputs and source lineage |
| Media | A bounded asset/render pipeline | Asset rights/provenance, duration/format checks, reproducible composition, visual/audio review and explicit generation costs |
| Trading research | Historical analysis, simulation and paper execution | Point-in-time data, leakage checks, frozen out-of-sample evaluation, complete search ledger, costs/slippage assumptions and order reconciliation |

Trading research and live trading are separate capabilities. Research workers
must not possess live broker execution credentials. Positive historical results
do not establish future profitability. Live execution requires its own adapter,
explicit authorization, position/exposure limits, stale-feed handling, kill
switch, broker-state reconciliation and independently tested operational policy.
Software correctness, statistical evidence, and authorization are three distinct
gates; none substitutes for the others.

Every real action adapter must define receiver-side idempotency scope and
retention, response-loss behavior, authoritative outcome queries, compensation
where possible, and permitted identities. Test ambiguous success and delayed
receipts against the actual provider sandbox. An intent recorded in PostgreSQL
is not proof that a payment, message, deployment, or order happened exactly once.

## What should make GraphOS distinctive

Prioritize an inspectable chain from requirement to task, input, artifact,
verification, release and observed outcome. Combine adaptive delegation with
measured cost and defect reduction; retain the ability to use one agent when it
is the stronger choice. Publish reproducible results for the supported scope.
Those are concrete engineering differentiators. "Unprecedented," universal
superiority, and perfect reliability remain unsupported claims unless evidence
commensurate with those claims is produced.
