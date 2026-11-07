# Live validation and resume procedure

On 2026-11-07 the configured environment key authenticated with AI Gateway. The
live model catalog still matched the pinned catalog hash. The dedicated key's
budget was $1 with no reset, under the session's $5 total authorization.
Gateway budgets are soft caps, not hard invoice ceilings.

## First real attempt

Command:

```sh
.venv/bin/python scripts/live_acceptance.py --execute --max-attempts 1 --budget 1000000
```

The harness started a separate controller and compiled eve service, submitted
one live build, and stopped both owned processes afterward. Gateway rejected the
request with HTTP403 `customer_verification_required`: the Data Analyst Mike team
must have a valid payment card on file. No candidate was produced, no fixture was
substituted, and no automatic retry occurred.

- [Original attempt](../evals/results/live-20261107T182936-2e2a9890.json)
- [Provider blocker and spend observation](../evals/results/live-blocker-20261107.json)

Gateway reported $0 used. A subsequent credits read showed $5 available; that
balance alone does not prove the payment-verification restriction is cleared.
GraphOS retained 1,000,000 microdollars as a conservative uncertain charge and
paused the run in `RECONCILIATION_REQUIRED`. This is an accounting reservation,
not a confirmed $1 provider debit. Do not erase or silently refund it merely
because the request failed or the budget dashboard shows zero.

## Resume order

1. The team owner completes payment-card verification in Vercel. Never put card
   information or model keys into chat, task payloads, logs or version control.
   Credit purchase and automatic top-up are separate decisions.
2. Inspect the retained session error and Gateway usage. Reconcile the paused
   attempt only with sufficient provider evidence using the existing operator
   receipt endpoint. Retain the receipt and its basis. If cost remains uncertain,
   leave the run paused and count the full reservation against session headroom.
3. Verify remaining session authorization and the dedicated key's active budget.
   Run mandatory checks before the next live request. The harness rebuilds the
   adapter without live credentials and rejects a source change during that build. Do not restart a potentially spending
   durable session to bypass reconciliation.
4. Run one new explicitly authorized attempt with the command above. The harness
   does not load a private key fallback: it uses configured environment credentials.
   It disables fixture submission, scopes credentials to the model server, retains
   every attempt, and halts on uncertain accounting.
5. Only a submitted candidate proceeds to the independent Docker/Chromium suite.
   Only a verified candidate is exported. Inspect its product behavior and record
   Gateway receipts using recorded generation IDs when available.
6. After a passing initial slice, exercise bounded repair with a settled cost
   history, an explicit two-attempt allowance, and sufficient reservation headroom.
   Each repair must receive current failed evidence and earn new verification.

The harness emits a unique result JSON under `evals/results/` and accepted
exports under `.state/live-deliveries/`. It binds results to a source digest that
includes the controller, verifier, model instructions, adapter, tests and locks.
An interrupted or source-changing run cannot be promoted to a clean pass.

## Implemented after the first attempt

Retry claims now include the latest rejected candidate and bounded verifier
diagnostics only for the same task input, revision, suite and policy. A current
lease controls reads; the worker verifies the artifact hash. Failure text is
untrusted context, never authority to change tools, paths or acceptance criteria.
Failures before model dispatch are known zero cost; failures after dispatch are
conservative unless actual cost is reported. The worker checks the complete JSON
request against the adapter's 128 KiB limit before spawning it, including escaping
and UTF-8 bytes. Oversized repair context is rejected with known zero cost; files
are never silently truncated. Thus some valid maximum-size output bundles still
exceed the narrower repair-context limit and require an operator to reduce scope.

The broker retains Gateway generation IDs from eve's public `model.settled`
events and costs from `usage.recorded`. Missing IDs remain explicit nulls.
Malformed, duplicate and orphan receipts fail accounting validation. Receipt
lookup is read-only and separate from generation; Gateway event cost and actual
account debit are distinct measurements.

These changes strengthen a single supported task-list profile. They do not
establish live model quality, arbitrary application generation, multi-tenant
production security, or a reliability percentage. Remaining milestones are in
[the implementation roadmap](implementation-roadmap.md).
