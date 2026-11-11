# Reviewed GraphOS checkpoint — November 11, 2026

Qualification: offline code validated; original-turn crash recovery remains pending.
Reviewed source digest: `a6d0df26af54fd205d40728574423a2207af5a464b61dc4e83b5d08cf392e55e`.
Base commit: `5d367595cab7b168aae9d70c0a97059e0e777203`.

This checkpoint strengthens focus-state verification and precise repair diagnostics,
rejects unchanged repair candidates against bound failed evidence, and persists
scoped early runtime receipts. A narrow read-only abandonment resolver checks the
retained session/model/generation identity after Eve restores pre-step context.
It restores neither dispatch authority nor missing usage or settlement state.
A completed session lifecycle event cannot certify model success, cost settlement
or artifact release. Missing or conflicting identity fails closed.

Independent design, patch and evidence reviews approved offline qualification.
Recorded local gates passed: 80 Node tests; 344 Python tests plus 28 subtests;
25 reference tests; 42 targeted receipt tests (a subset); typecheck, build, lint,
and fake-provider runtime smoke/callback scenarios. No final failures or skips.
Original report SHA-256:
`b631bdb5953a9ed6d7a6bdcc65b153fa0386f4c650dc9fa59dbf0559500e4145`.
Independent closure review SHA-256:
`188b83febbf2f36950974a8a263949612fe547e24ee13130209423432935915b`.
These refer to retained local evidence, not publicly available raw runtime data.

Historical denominators remain separate:

| Experiment | Planned | Dispatched | Accepted | Failed/incomplete | Undispatched |
|---|---:|---:|---:|---:|---:|
| Original pilot | 6 | 3 | 0 | 3 | 3 |
| Reconnected pilot | 6 | 2 | 0 | 2 | 4 |
| Structured pilot | 6 | 6 | 1 | 5 | 0 |

The separate task-list and inventory repair demonstrations each exhausted two
attempts with zero accepted; inventory repeated the candidate. Terminal-boundary
restart had two harness attempts: one setup failure and one reached/passed restart.
Mid-generation restart remains **0/2 passed, two failures**. The 120-second test
stalled before runtime ownership eligibility; the 1,020-second test observed the
original turn reexecuting but failed at missing model binding before its dispatch
fence. Neither becomes a pass because offline tests pass. Focus calibration was
15/15 expected controls on the preceding source, not generation quality evidence.
Original UNKNOWN cost observations and later reconciliation remain distinct.

Next gate: CI on the actual pushed checkpoint, then one independently reviewed
fake-provider mid-generation restart drill, at most 1,020 seconds including setup
and cleanup. Keep 860-second runtime ownership and declare a 600-second fixture
claim. Require positive original-turn recovery and actual pre-provider rejection,
exactly one durable fetch count, exact receipt identity and no fabricated usage.
Exactly one expiry classification must preserve exposure: spent 0/reserved 1,000,000
becomes conservative spent 1,000,000/reserved 0, uncertainty retained; this is not
verified provider settlement. Later lifecycle completion remains a raw fact.
Stop on second fetch, receipt conflict, unexpected identity/accounting change,
release or deadline; retain failures and do not automatically rerun.

Unexpired replay, registration-to-dispatch races, settlement enforcement and host
loss remain separate gaps. Two fresh live repair demonstrations and broader held-out
evaluations remain open. No production-readiness claim or merge authorization.
Raw stores, journals, grants, credentials and historical runtime traces are excluded
from this checkpoint. The PR remains draft. Future reports identify their own source
and build; no new test run is implied by this historical local qualification summary.
