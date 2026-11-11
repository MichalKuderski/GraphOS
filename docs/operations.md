# Operations

## Local execution

`python3 scripts/setup.py --with-agent` creates a real PostgreSQL service and
builds the trusted verifier. It writes private random credentials to
`.state/local.env` with mode 0600 and never prints them. Setup does not start
model generation. Re-running setup retains the database volume and credentials.

Start the API using:

```bash
.venv/bin/python -m graphos --env-file .state/local.env serve --port 8030
```

Start the eve server separately according to `agents/eve/README.md`. It uses port
3001 and its own bearer token. Model credentials belong only to that server.
Do not pass operator, builder, verifier, database or release credentials to it.

Run all mandatory Python/platform gates without silently skipping integration:

```bash
.venv/bin/python scripts/check.py
```

## Deployment

`compose.yaml` provides PostgreSQL plus the non-root API container. Supply private
environment values named in the file. The API port is published only on loopback.
Workers run separately; the API does not receive the Docker socket or model key.
Build the verifier on its dedicated execution host and configure the same image
digest in the API and verifier environments. Their suite/policy hashes must match.

The supplied Compose configuration is a single-host starting deployment. It is
not high availability, public TLS termination, automatic backup, or a managed
worker fleet. A public deployment requires trusted host configuration, TLS,
external identity as appropriate, monitoring, backups, and an isolation review.

Reserve and monitor worker-host storage before starting containers. In this
managed environment, Docker's VFS driver required full init/writable image
copies, and failed starts left orphaned copies; see `storage-recovery.json`.
The final suite passed after precise recovery. Prefer a supported copy-on-write
storage driver on a dedicated execution host for wider operation. Automated disk
admission, host recovery and cross-run resource scheduling are not implemented.
Do not turn the one-time recovery into a broad deletion job over Docker storage.

## Model budgets

Amounts are integer microdollars. 1,000,000 means $1. Each dispatch reserves a
maximum local amount; settlement records actual usage. Uncertain failures consume
the reservation. A known overrun records the full amount and blocks new dispatch.
Do not reset that state merely to make a failed run appear successful.

A provider-side budget on a dedicated credential is required to bound actual
charges across model retries, interrupted requests, and replay. Setting a local
environment variable acknowledging $5 does not configure or prove that control.
Never raise the user's approved total without their authorization.

Late provider totals are reconciled through the operator cost-receipt endpoint.
Its input is an authoritative total for one build attempt, not an increment.
The controller deduplicates the receipt and adjusts previously conservative
accounting. It does not verify provider authenticity itself; the operator must
obtain trustworthy billing evidence. Conflicting totals require an explicit
correction policy, not overwriting history.

## Recovery and cancellation

An interrupted build remains leased until PostgreSQL's clock determines expiry.
Replacement attempts receive a new fence/token. The old worker cannot submit or
read artifacts afterward. Retrying an external operation requires a separate
effect protocol; task retry is not permission to duplicate an external action.

If an effect dispatch response and its token are lost, the operator can claim a
new reconciliation token for the same dispatch attempt. This marks uncertainty
and invalidates old receipt tokens without authorizing another dispatch. Query
the real provider before asserting CONFIRMED or NOT_APPLIED. No live effect
adapter is included in this milestone.

Cancellation blocks new work and preserves known/uncertain effects and cost.
It cannot undo an action already committed by an external system.

## Backups and upgrades

Back up PostgreSQL and the content-addressed artifact directory as a coherent
set. Because artifacts are immutable and committed before their database
references, take the database snapshot first, then copy artifacts while preventing
garbage collection. Encrypt and restrict the backups. Restore into an isolated
database and storage directory and verify every accepted manifest before use.
Define and test RPO/RTO for the actual deployment; a local restart test is not a
disaster-recovery guarantee.

A reproducible [local restore drill](restore-drill.md) is implemented:

```bash
.venv/bin/python -m scripts.restore_drill --output docs/restore-validation.json
```

The [measured run](restore-validation.json) restored ten GraphOS tables and
eighteen referenced CAS objects into a fresh retained scratch database, compared
source/restored row and schema identities, and verified four release manifests.
It did not replace the source, resume workers, test remote backup encryption, or
establish production RPO/RTO. The scratch database and private `.state/drills/`
capture are retained for inspection. Do not enable workers against the restored
database before recovery fencing and external-effect/cost reconciliation.

Migrations are versioned and checksummed; changing an applied migration is
rejected. Back up before upgrades. A verifier source, image, or policy change
changes its identity. Restart the services with matching configuration, revise
affected runs, and rerun verification. Never rewrite old evidence to imply it
tested new code.

## Incident triage

1. Stop new dispatch for the affected run; preserve events and immutable artifacts.
2. Identify the exact revision, attempt, candidate, suite, policy and image.
3. Separate unknown external effects from failed computations.
4. Reconcile provider actions and costs before retrying or releasing reservations.
5. Add a regression case; promote fixes only after the relevant gates pass.

Do not log bearer tokens, lease tokens, Gateway keys, full environment variables,
or unrestricted model/provider responses. Logs and evidence need their own
retention and access policies.

## Receipt recovery

The current receipt protocol records a session and exact model-run intent before
provider dispatch. Only a first, nonduplicate intent ACK permits dispatch. An
intent whose ACK was lost is never permission to repeat the model call. The first
trusted Gateway generation ID is captured before its chunk is forwarded to Eve.
Model text cannot supply that identity. Usage and terminal facts are independent
of final candidate output; capture does not charge/refund a run, release a
reservation, clear cost uncertainty, or authorize delivery.

Configure `GRAPHOS_RECEIPT_API_URL` as a stable trusted API origin and
`GRAPHOS_RECEIPT_OUTBOX_DIR` on a private retained volume accessible only to the
Eve worker/recovery operator. The default is `.state/receipt-outbox` under the Eve
working directory. Direct callback transport ignores ambient proxies and rejects
redirects. Journal records contain scoped receipt capabilities: directory mode
0700 and record mode 0600 are mandatory; do not upload them as test evidence.
Record contents and directory links are fsynced before callback transmission.
Committed records remain after ACK so identical facts can be recovered after an
unknown response. Recovery does not call a model or make accounting transitions.

With provider credentials absent, replay one attempt's committed journal:

```sh
cd agents/eve
env -u AI_GATEWAY_API_KEY -u VERCEL_OIDC_TOKEN node dist/src/recover-receipts.js \
  --run-id RUN_ID --attempt-id ATTEMPT_ID
```

The origin/outbox settings must refer to the original trusted service and volume.
To recover a retained usage/terminal event that never entered a handler, provide
the original private envelope, existing Eve session ID, and trusted broker URL:

```sh
env -u AI_GATEWAY_API_KEY -u VERCEL_OIDC_TOKEN node dist/src/recover-receipts.js \
  --envelope-file /private/original-envelope.json \
  --session-id EXISTING_SESSION_ID --eve-url http://127.0.0.1:3001
```

This path uses the configured `GRAPHOS_EVE_TOKEN` only to read an authenticated
snapshot. It does not create/send/end/cancel a session, restart uncertain work,
register new work from a snapshot, or settle costs. The API checks the existing
grant/session/model binding. Terminal capture uses the channel handler because
Eve 0.91's terminal publication path does not invoke authored agent hooks.
Conflicts or pending journal entries stop recovery for operator investigation.
Afterward, inspect operator receipt history and accounting separately. A runtime
cost report or generation lookup ID is not a reconciled provider invoice.

Bounded guarantee: process death after journal commit is covered on the retained
volume, as are callback failure before commit and committed callbacks with lost
ACKs. A crash before a generation journal commit can still lose an observed ID;
an unfinished `.tmp` file is not a committed record. Retained Eve usage/terminal
events have a separate recovery path, but an ID withheld before reaching Eve may
not. Host/volume loss, automated recovery scheduling, journal archival/sharding,
and account-wide invoice reconciliation remain open. The current scan is limited
to 4096 committed records and 16 per selected attempt; reaching the limit fails
closed. Broader operation requires retention/archival and a tested persistent
volume policy. None of these checks establishes universal reliability.
