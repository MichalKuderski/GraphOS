# Live generation and repair validation

On 2026-11-07 GraphOS completed a real model-generated task-list app and a separate
controlled persistence repair. Both resulting candidates passed all eight trusted
Docker/Chromium checks and were exported with immutable release manifests.
This establishes these observed executions of one disclosed contract, not a
success rate, arbitrary app capability, or production certification.

## Observed results

| Experiment | Result | Model charge in GraphOS ledger | Evidence |
|---|---|---:|---|
| Initial live build after adapter fixes | Eight checks passed; release exported | $0.010675, rounded upward | [Live result](../evals/results/live-20261107T185333-be67cfb4.json) |
| Controlled persistence fault and one live repair | Fault rejected; exact rejected candidate/evidence supplied; new verification passed eight checks | $0.007619, rounded upward | [Repair result](../evals/results/controlled-repair-b1f44a1b1f0a4a3ba472194c5919a3cc.json) |

The repair deliberately disabled `Storage.prototype.setItem` in the accepted
model-generated candidate. Its fixture provenance explicitly identifies the
mutation and source artifact. The verifier rejected `local_storage_reload` and
blocked release. Exactly one real model repair followed; its new candidate earned
new verification. The injection controller admitted fixtures only for the seed;
it was stopped before a separate fixture-disabled controller ran live repair.
This is a controlled fault experiment, not a naturally occurring model failure.

Read-only Gateway generation lookups confirm model/provider identity and charges:
[initial success receipts](../evals/results/live-success-receipts-20261107.json)
and [repair receipts / final spend](../evals/results/live-final-spend-20261107.json).
The key's reported total spend, including failed model-backed attempts, was
**$0.05466171**. Its $1 non-resetting budget remains unchanged and is a soft cap.
No credit purchase, automatic top-up or billing change was performed by the agent.
The total session authorization remains $5.

## Retained failures and fixes

Earlier attempts are kept, not removed from the denominator:

1. [Payment-card rejection](../evals/results/live-20261107T182936-2e2a9890.json):
   HTTP403 `customer_verification_required`. The user completed card verification.
2. [Free-tier model rejection](../evals/results/live-20261107T184037-496b2df4.json):
   HTTP403 `no_providers_available` for GPT-6 Luna, before any provider attempt.
   Vercel's current model directory lists the explicitly selected replacement,
   `openai/gpt-5.1-codex-mini`, as available to the free tier. Selection metadata
   and original selection are retained under `agents/eve/`.
3. Three model-backed builds failed at the adapter boundary before submission:
   [first](../evals/results/live-20261107T184241-7cbb5ded.json),
   [second](../evals/results/live-20261107T184759-07e20633.json), and
   [third](../evals/results/live-20261107T185003-b8d7f30f.json).
   Costs were reported and recorded. No candidate received acceptance or release.

The first two Gateway rejections initially retained a conservative $1 uncertain
ledger reservation each. They were subsequently reconciled to zero through the
operator receipt endpoint, using the explicit pre-provider Gateway403 responses,
terminal workflows, zero spend observed after those rejections, and the dedicated
key's total charge matching all settled model-session charges. This is an audited
operator reconciliation, not a fabricated provider invoice or a rule that failed
requests are free. The rejected runs remain exhausted and cannot silently retry.
[Reconciliation evidence](../evals/results/gateway-rejection-reconciliation-20261107.json)
records the basis and receipts; no uncertainty remains for these two attempts.

Two eve 0.91 lifecycle behaviors required fixes. Private sessions defaulted to
zero history retention, deleting evidence at completion. GraphOS now explicitly
uses the Workflow World's default retention in its private store. The actual
retention period and production cleanup policy remain operator responsibilities.
Also, end-receipt streams do not follow future events; an immediate result read
can precede command settlement. The broker now waits within its existing deadline
for an applied receipt and completed session event matching that exact end
delivery. It does not treat HTTP409/410 or unrelated completion as success.
A credential-free compiled-runtime regression tests this immediate read boundary,
retained history, wrong-delivery rejection and zero model calls.

The retained third failed session yielded valid generated files and usage when
read without a new model call; [recovered provider receipts](../evals/results/live-recovered-receipts-20261107.json)
are preserved. Those files were not retroactively released. The successful live
run exercised the corrected path from new generation through export.

## Reproduction and limits

After inspecting remaining authorization, provider access and budget:

```sh
.venv/bin/python scripts/live_acceptance.py --execute --max-attempts 1 --budget 1000000
.venv/bin/python scripts/controlled_repair.py PATH_TO_ACCEPTED_LIVE_EXPORT --execute
```

Both commands spend model credits. The first rebuilds the adapter without live
credentials, rejects source changes during the build, and exports only verified
candidates. The second validates the seed's live provenance, manifest and bytes,
checks authoritative release identity, injects a declared defect, and permits at
most one real model repair. Each emits a unique result JSON and preserves failure
and cost history. Neither is an unattended benchmark or session-wide invoice cap.

Repair context is restricted to the latest rejected candidate for the current
revision/input/suite/policy. Current leases control artifact reads; hashes are
rechecked. Diagnostics are untrusted context. Complete serialized requests above
128 KiB fail before model dispatch with known zero cost; files are not truncated.
Some valid maximum-size output bundles therefore exceed the narrower repair limit.

Model credentials reach only the model service. Candidate execution remains in
the pinned, offline, non-root Docker verifier; Docker still shares the host kernel
and Chromium's process sandbox remains disabled under the recorded policy.
The public profile still supports only the fixed task-list contract. Wider task
families, representative held-out evaluation, stronger isolation, identity,
backup/restore operations and deployment controls remain separate roadmap gates.

## Product review gap

The initial accepted app's desktop/mobile visual review found no horizontal
overflow or JavaScript errors, but measured normal-text contrast below 4.5:1 for
delete buttons (2.77:1) and completed tasks (2.45:1). Full task names repeated in
delete buttons also crowd rows. The current suite omits contrast, so its passing
certificate must not be presented as a complete accessibility audit. The controlled
repair targets persistence and does not claim to fix those styling issues. The
next static-web profile revision should add validated visual/accessibility checks
and corresponding negative controls before wider product-quality claims.
See [bound visual findings](live-visual-review.json).
