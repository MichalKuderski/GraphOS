# GraphOS first production milestone contract

This is the shared implementation boundary for collaborating developers. The
foundation blueprint is in docs/foundation/blueprint.html. Implement real
PostgreSQL transactions and immutable artifacts; do not label fixture mode AI.

## Module boundaries

- graphos/ledger.py, graphos/migrations/*.sql, tests/test_ledger.py: durable state.
- graphos/artifacts.py, graphos/sandbox.py, graphos/profiles.py,
  graphos/worker.py, tests/test_workers.py, profiles/: execution and verification.
- agents/eve/: model integration.
- tests/test_acceptance.py, scripts/acceptance.py, evals/: integration evidence.
- graphos/api.py, graphos/config.py, graphos/__main__.py, dashboard, dependencies,
  Docker/Compose, CI and root docs: service composition and operations.

Use Python 3.12+, FastAPI/Pydantic2, psycopg3, PostgreSQL 17. Root installs shared
Python dependencies in .venv. Node 24 agent uses version-matched eve/AI SDK docs.
All monetary accounting is integer budget units (microdollars for live model
usage); test fixtures must record provenance and cannot count as live success.

## Ledger API (Python; root imports Ledger and Conflict from graphos.ledger)

Ledger(dsn: str); migrate() idempotent, versioned migration with a lock.
create_run(spec: dict, budget: int, idempotency_key: str) -> dict
  spec = {name, profile, requirements:[str], tasks:[{key, objective,
  depends_on:[key]}], suite_hash:str, policy_hash:str, max_attempts:int=3}
  reject empty/duplicate/cyclic tasks and unknown dependencies. Require bounded
  positive limits, hashes and profile; root profile registry supplies suite_hash.
get_run(run_id) -> dict including tasks, events, budget, spent, reserved,
  revision, spec_hash, state, profile and spec.
list_runs() -> list[dict]
claim_build(run_id, worker_id, reserve: int, lease_seconds: int=120) -> dict|None
  Returns {run_id,task_id,task_key,epoch,revision,token,input_hash,expires_at,
  objective,requirements,profile,suite_hash,policy_hash,dependencies,
  reservation}; dependencies are accepted candidate manifest hashes.
submit_build(run_id,task_id,token,epoch,revision,input_hash,candidate_hash,
             actual_cost:int,provenance:dict) -> dict
  Only active current lease; duplicate exact submission idempotent. State
  SUBMITTED (never ACCEPTED). Reuse tokens across retries cannot forge state.
fail_build(run_id,task_id,token,epoch,reason,actual_cost:int,cost_known:bool) -> dict
claim_verify(run_id,verifier_id,lease_seconds:int=120) -> dict|None
  Claims SUBMITTED tasks with independent verifier id; returns same bindings
  plus candidate_hash and producer_id and unique verification token.
submit_verification(run_id,task_id,token,epoch,revision,input_hash,
                    candidate_hash,suite_hash,policy_hash,passed:bool,
                    evidence_hash,report:dict) -> dict
  Bind verifier to current candidate/input/suite/policy. Pass -> ACCEPTED.
  Fail -> PENDING if attempts remain, else EXHAUSTED. Never accept stale report.
revise_run(run_id,spec:dict,expected_revision:int) -> dict
  Full run revision for milestone1: conservatively invalidate all tasks and
  receipts; retain history. Consume outstanding build reservations, fence leases.
cancel_run(run_id) -> dict
  Fence workers, consume outstanding reservations, stop new dispatch, preserve
  receipts; run CANCELLED. External effects remain independently reconcilable.
release_manifest(run_id,expected_revision=None,expected_spec_hash=None) -> dict
  Records or retrieves a release receipt; no deployment. Require all tasks ACCEPTED and
  current evidence; return exact candidate/evidence/input/suite/policy bindings.

Atomic ledger mutations lock a run row before task/reservation changes. Expired
build attempts conservatively consume reservation. Never return it just because
a worker stopped reporting. PostgreSQL server time is authoritative for leases.
Events commit in the same transaction. Outbox records exist; an external event
dispatcher is not implemented.

reconcile_cost(run_id,attempt_id,receipt_id,actual_cost) -> dict
  Operator asserts an authoritative total for one build attempt. Exact retries
  are idempotent; conflicting or second receipts are rejected. Apply the delta
  against its previous charge without changing task acceptance or revision.
  Unknown cost pauses dispatch until reconciliation; a known overrun records
  the full amount and blocks further dispatch. This does not verify an invoice
  or establish a provider-side spending cap.

Effects (no real external dispatch by core):
prepare_effect(run_id,key,payload_hash,receiver_deduplicates:bool) -> dict
begin_effect(run_id,key) -> dict incl attempt/token; ambiguous non-deduped retry
  rejected. Same operation key never permits a different payload hash.
resolve_effect(run_id,key,attempt,token,outcome) -> dict
  outcomes CONFIRMED/UNKNOWN/NOT_APPLIED; stale attempt cannot clear uncertainty.
  NOT_APPLIED requires authoritative reconciliation at the adapter boundary.
claim_effect_reconciliation(run_id,key) -> dict
  Rotate the receipt token for the same dispatch attempt, without authorizing
  another external action. This remains possible after cancellation/revision.

## Artifact and verification contracts

ArtifactStore(root: pathlib.Path)
put_bundle(files: dict[str,str]) -> str: manifest digest; reject absolute paths,
  traversal, symlinks, control chars, reserved names, excessive files/bytes.
get_bundle(digest: str) -> dict[str,str]: recompute every content/manifest hash.
put_json(value: dict) -> str and get_json(digest) -> dict for evidence.
materialize(digest, destination: Path) -> None: destination must be new/empty.
Bundles use normalized POSIX paths. All files UTF-8 for initial static-web.

profiles.get_profile(name) -> dict {id,status,suite_hash,policy_hash,
  required_files,acceptance_criteria,...}. Only static-web is active. Other
profiles games,bots,data,media,trading-research are contract-only, disabled for
execution. Do not present these as generated or validated capabilities.
HTTP admission requires the active profile's exact registered task template and
requirements. The generic ledger DAG alone does not certify arbitrary products.

sandbox.verify_bundle(files: dict[str,str], requirements:list[str]) -> dict
  {passed:bool, checks:[{name,passed,detail}], runner, duration_ms,...}
  Never run arbitrary code on host. Docker with network none, non-root,
  read-only root, limits, no-new-privileges, cap-drop ALL, no secrets/socket.
  Fail closed if Docker unavailable. Trusted verifier suite is outside candidate.
  Initial browser contract: index.html, app.js, styles.css; a working accessible
  task-list app with add, complete, filter, delete, persistence, empty input and
  literal HTML-looking text. The spec explicitly requests these behaviors.
  Fixed trusted suite: users cannot inject shell commands or test code.

worker.py supplies build_once(api_url,token,run_id,builder,worker_id) and
verify_once(api_url,token,run_id,worker_id), or equivalent documented CLI.
Builder modes: fixture (explicit deterministic fixture for integration tests),
eve (real model adapter). Fixture is never silently chosen when model auth fails.
Live builder output is {files: Record<string,string>, usage:{...}, provenance:{...}}.
Broker owns ArtifactStore; submit endpoint stores bundle then ledger candidate.
Verifier gets exact bundle from authenticated API and stores report via API.
No candidate HTML is served from control-plane origin; downloads are attachments.

## HTTP contract (root implements)

Bearer tokens by role: operator, builder, verifier (distinct >=32-byte secrets).
No default tokens in production. Health reveals no secrets. Dashboard read API
requires operator token; token only in browser memory, never localStorage/URL.
Routes under /v1:
POST /runs {spec,budget,idempotency_key}; GET /runs; GET /runs/{id}
POST /runs/{id}/revise {spec,expected_revision}; POST /runs/{id}/cancel
GET /runs/{id}/release
POST /runs/{id}/claim/build {worker_id,reserve,lease_seconds}
POST /runs/{id}/claim/verify {worker_id,lease_seconds}
POST /runs/{id}/tasks/{task}/submit {token,epoch,revision,input_hash,files,
  actual_cost,provenance}
POST /runs/{id}/tasks/{task}/fail {token,epoch,reason,actual_cost,cost_known}
POST /runs/{id}/tasks/{task}/verify {token,epoch,revision,input_hash,
  candidate_hash,suite_hash,policy_hash,passed,report}
GET /artifacts/{hash} (authenticated, JSON bundle; role scope checked)
GET /profiles (authenticated)
POST /runs/{id}/costs/reconcile {attempt_id,receipt_id,actual_cost} (operator)
Effects endpoints are operator-only; no real effect adapter in milestone1.

Builder/verifier artifact reads require an active lease with run, task, token,
and epoch headers. Builders may read accepted dependencies; verifiers may read
only their claimed candidate. Operators have tenant-wide read access.

API enforces body limits, rejects extra fields, uses no CORS by default, checks
trusted hosts, binds localhost by default. Logs never include bearer/lease tokens.
The demonstration uses both a deterministic fixture and real model mode only
when auth exists; results label their provenance. No unsupported success claims.
