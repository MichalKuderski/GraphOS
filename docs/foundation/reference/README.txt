GraphOS reliability reference model
==================================

This is a small executable specification of orchestration invariants. It is NOT
a completed GraphOS agent system, production scheduler, or distributed runtime.
It performs no LLM calls, network requests, deployment, or financial trades.

Requires Python 3.10+ and only its standard library.

Run from this directory:
  python3 -m unittest -v
  python3 graphos_kernel.py

The demo prints JSON showing a stale worker rejected after lease expiry, a
downstream worker rejected after an upstream revision, an external action left
UNKNOWN after a timeout rather than blindly retried, and a stale reconciliation
report rejected after a newer dispatch has timed out.

Implemented contracts
---------------------
* Tasks are added in dependency order, so the task graph is acyclic. A task runs
  only after every dependency has current passing verification.
* Task inputs and immutable artifact bytes have SHA-256 identities. Each attempt
  captures its dependency versions. Evidence binds an artifact, input signature,
  and test revision. A different named actor must verify the producer's work.
* Each task has a monotonic fencing epoch and explicit attempt limit. Expired,
  superseded, and duplicate completions cannot publish results.
* Input changes invalidate every dependent transitively, including active leases.
  Changing a test revision retains unchanged root artifact bytes but discards its
  evidence and invalidates downstream work. A fresh test result is required.
* Repairs retain the attempt counter. An explicit input/test revision starts a new
  bounded attempt series. The run-wide credit limit still applies across revisions.
* Claims reserve integer credits before starting. Actual charges must not exceed
  the reservation. Expired/invalidated work conservatively consumes the whole
  reservation; this prevents unknown old spend from funding extra work.
* External actions use immutable intent keys. Timeouts become UNKNOWN. Retrying
  UNKNOWN is permitted only when the receiver is assumed to deduplicate that key,
  or authoritative reconciliation proves the original attempt cannot take effect.
* Every dispatch returns an immutable token containing its intent key, attempt
  number, and payload hash. Timeout, confirmation and reconciliation require the
  current token. Delayed reports from older attempts cannot resolve a newer
  attempt's uncertainty or allow another unsafe dispatch.

States
------
Task: PENDING -> READY (derived view when dependencies verified) -> RUNNING ->
PRODUCED -> VERIFIED or REJECTED. Failed/rejected attempts may return to PENDING;
the attempt limit leads to EXHAUSTED. A revision invalidates affected tasks.

External action: PREPARED -> IN_FLIGHT -> APPLIED or UNKNOWN. UNKNOWN must be
reconciled, or retried with the same intent only under receiver deduplication.
NOT_APPLIED means authoritative, terminal absence, not merely an absent receipt
or a stale read while the original action may still complete.

Explicit limitations and assumptions
-----------------------------------
* All state is in memory. There is NO persistence, restart recovery, transaction
  isolation, shared queue, durable event log, outbox, database, or cross-process
  synchronization. Public mutations assume sequential atomic execution.
* Time is supplied by the caller and assumed trustworthy. Production leases need
  an authoritative clock and transactional compare-and-set on epoch/revision.
* Agent names and evidence are supplied values. There is NO authentication,
  signature verification, sandbox, network policy, tool permission enforcement,
  independent test runner, or trusted spend meter. Identity separation here does
  not establish statistical independence or prove that tests were actually run.
* The budget model checks declared credits, not a provider invoice. A real tool
  gateway must cap spending; an uncapped worker can exceed its reservation.
* Receiver idempotency is an assumption, not provided by a local dictionary. It
  must cover the same key, payload, account, operation, and retry retention window.
  The code makes NO exactly-once external-effects claim.
* Artifact hashes provide content identity, not a proof of correctness or trust.
  JSON canonicalization here is local to this model, not a cross-language spec.
* No dynamic graph edits, fan-out scheduler, resource quotas, capability graph,
  graph database, learned routing, model selection, or memory retrieval are built.
* There is no evidence expiration policy or mutable external-environment digest;
  production evidence also needs environment, toolchain, test-run and policy IDs.
* The event list is a demo trace, not a sufficient event-sourcing/replay format.
* Test success validates these scenarios only; it does not measure general agent
  capability, complete correctness, production readiness, or financial returns.

Production adaptation
---------------------
Use this as a testable contract to port into the existing GraphOS runtime. Store
claims, reservations, fencing epochs and state transitions in transactions;
execute tools behind an authenticated, budget-enforcing gateway; store versioned
artifacts; run trusted verifiers; persist dispatch intent before external actions;
and test crashes and concurrency against the actual database/runtime. Choose one
durability owner. Do not infer those guarantees from this in-memory model.
