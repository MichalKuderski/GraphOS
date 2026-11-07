# GraphOS eve builder

A real eve `0.91.0` agent, compiled by `eve build`, and a broker using the public
`eve/client` SDK. This implements the first **static-web task-list profile only**.
It does not implement arbitrary apps, trading, games, deployment, or release.

```text
GraphOS build lease -> broker -> authenticated eve server -> AI Gateway
                    <- files + recorded usage + provenance <-
GraphOS artifact store -> separate Docker/browser verifier -> ledger acceptance
```

## Status and versions

A real provider-backed build has now generated a task-list app, passed all eight
independent Docker/Chromium checks, and exported an evidence-bound release.
The retained attempt history includes Gateway access rejections and adapter
retirement failures; these are not omitted from the record. See
`../../docs/live-validation.md` for exact runs, receipts and limitations.

Dependencies and lockfile are pinned: Node 24, eve `0.91.0`, AI SDK `7.0.164`,
Zod `4.6.7`, just-bash `3.6.0`. At verification, npm's latest tag pointed to
`eve@1.0.0-rc.6`; `0.91.0` was the latest non-prerelease package. Its documentation
still calls the framework **preview**, and its Nitro dependency is a beta. A
stable-looking package version is not a framework stability guarantee. Review
eve's migration notes before upgrades; persisted sessions bind to its runtime.

## Build and offline verification

```sh
cd agents/eve
npm ci --ignore-scripts
npm run typecheck
npm test
npm run build
npm run test:runtime
```

In the managed Codex environment use `npm_config_cache=/workspace/.cache/npm`.
When an environment provides HTTP(S) proxy settings, Node 24 can use them with
`NODE_USE_ENV_PROXY=1`; preserve its configured CA path. Do not disable TLS checks.

`test:runtime` starts the compiled server on loopback port 3009, supplies an
explicit test-only broker credential, excludes model credentials, and stops it.
Unit fixture strings are test inputs; the production broker has no fixture path.

## Start the service

The eve server is a separate long-lived service because the public framework API
does not expose an in-process agent runner. The CLI never secretly starts a
runtime or reuses an earlier session. Run the service as an unprivileged process.
Its persistent state is under `.eve/`; do not share it across unrelated deployments.

Configure the server's `GRAPHOS_EVE_TOKEN` with a distinct random secret of at
least 32 bytes. Configure the same broker token in the GraphOS builder process.
Do not reuse GraphOS operator, builder, verifier, or lease tokens for this role.

```sh
npm run eve:start
```

This listens on `127.0.0.1:3001` with schedules disabled. Keep it on loopback or a
private, authenticated HTTPS service boundary. The broker defaults to this URL;
`EVE_SERVER_URL` may select an explicit HTTPS origin. Plain HTTP is permitted only
for loopback. The broker rejects credentials in URLs and redirects.

For live generation, the **server**, not the broker subprocess, needs either
`AI_GATEWAY_API_KEY` or `VERCEL_OIDC_TOKEN`. No direct provider-key fallback exists.
Do not paste credentials into task JSON or commit them. The model has no secret
reading tools. Its just-bash environment is a virtual filesystem without host
mounts or native process access; no model tools expose it. Candidate JavaScript is
never executed by this service. Only GraphOS's independent verifier executes it.

## Live budget gate

This session authorizes at most **$5 total** model spend. Before enabling live
work, an operator must configure and verify a dedicated Gateway credential's
provider-side soft spending restriction, account for prior session spend, and verify
the selected model is accessible. The adapter has not performed those checks.
Then set server environment variables:

```text
GRAPHOS_LIVE_ENABLED=1
GRAPHOS_GATEWAY_BUDGET_USD=5
```

The second variable accepts a positive value no greater than five. These values
are an operator declaration, **not proof of the provider-side restriction**.
Without both declarations and Gateway authentication, ingress fails before model
work. The GraphOS run budget must also be at most 5,000,000 microdollars, with at
most three attempts. Each live attempt requires a reservation of at least
1,000,000 microdollars. Unused known reservation can be reconciled by the ledger;
uncertain attempts must remain charged conservatively. GraphOS pauses the run in
`RECONCILIATION_REQUIRED` until operator receipts settle every uncertain build,
including builds fenced by a revision; it does not automatically retry them.

Application limits are not a hard provider invoice cap. Each ordinary model run
has at most 16,384 output tokens and a 220,000-byte serialized prompt cap. Durable
observations stop new ordinary runs after three settled runs; only one turn per
session is allowed. The wrapper blocks repeated provider invocations through the
same model instance. A provider call is aborted after 90 seconds; the broker has
a 120-second deadline and up to ten seconds of cancellation/end cleanup. The
framework's idle timeout does not stop an active call.

eve's public agent configuration has no `maxRetries` option. Interrupted durable
steps may be replayed after a crash, and a provider may bill accepted work after a
timeout or failed cancellation. No local counter can resolve that ambiguity. A
fresh model instance can follow a durable replay. Gateway budgets are soft caps:
a request crossing the threshold can finish, and updates may be delayed.
Do not claim the run limits,
timeouts, reservation, or environment declaration independently enforce $5.

## Broker contract

Run this fixed command from any working directory, adjusting its repository path:

```sh
node /workspace/GraphOS/agents/eve/dist/src/cli.js < task.json
```

stdin is one JSON object, at most 128 KiB:

```json
{
  "claim": {"...": "the complete ledger build claim"},
  "profile": {"...": "the active get_profile('static-web') result"},
  "dependencies": [
    {"candidate_hash": "64 lowercase hex characters", "files": {"index.html": "...", "app.js": "...", "styles.css": "..."}}
  ]
}
```

The parser selects only needed claim/profile fields, removing the lease token
before any network request. Suite and policy hashes must match. The supplied
profile includes exact accessibility selectors and acceptance criteria. This
adapter checks bindings, while the authenticated GraphOS broker is responsible
for retrieving the authoritative profile and dependency artifacts.

Exit zero emits exactly one JSON object on stdout:

```json
{
  "files": {"index.html": "...", "app.js": "...", "styles.css": "..."},
  "usage": {
    "input_tokens": 100, "output_tokens": 200,
    "cache_read_tokens": 0, "cache_write_tokens": 0,
    "actual_cost_microdollars": 110, "model_runs": 1,
    "cost_source": "eve_gateway_usage_events"
  },
  "provenance": {
    "mode": "eve", "model": "openai/gpt-5.1-codex-mini",
    "independent_verification": "pending"
  }
}
```

The numbers above illustrate the schema, not a live measurement. Provenance also
contains runtime versions, session/delivery IDs, task/input/suite/policy bindings,
request and catalog hashes, and generation time. Files are exactly the three
listed paths, each at most 64 KiB UTF-8; output is at most 256 KiB. Structured
model output is validated again client-side. Runtime events supply usage and
provenance; the model cannot invent its accounting or certify acceptance.

Errors exit nonzero, with no success object on stdout, and one sanitized stderr
JSON record:

```json
{
  "error": "unreconciled_model_usage",
  "cost_known": false,
  "accounting": "consume_reservation_and_reconcile"
}
```

A known-cost failure additionally includes `actual_cost_microdollars` and
`accounting: "provider_reported"`. The worker must parse and record known actual
cost even if it exceeds the reservation, record an incident and halt further
dispatch; it must not silently replace that cost with a smaller reserved amount.
Missing costs, incomplete usage, or retry-ambiguous events fail instead of
pretending the request was free. Each reported dollar amount is rounded upward
to integer microdollars. Costs exclude infrastructure and independent verifier
resources. Client-read cancellation explicitly requests remote cancellation and
session retirement; inability to confirm those leaves spending uncertain.

## Model selection and evidence

The full unauthenticated live Gateway catalog was fetched from
`https://ai-gateway.vercel.sh/v1/models`: 498 entries on 2026-11-07. The exact
snapshot is `model-catalog.json`; `model-selection.json` records its SHA-256,
the selected entry's full tiered pricing, limits, and rationale.

The initial selection, `openai/gpt-6-luna`, was rejected by the team's free tier
after payment-card verification. Its original selection record is retained as
`model-selection-gpt6.json`. The explicitly selected replacement is
`openai/gpt-5.1-codex-mini`, listed by Vercel as available to the free tier and
advertising structured output and coding capabilities. Its standard catalog rates
are $0.25/million input and $2/million output tokens, with a 400,000-token context.
Actual Gateway receipts, not this catalog estimate, settle usage. No billing
settings, top-ups or automatic model fallbacks were enabled.

The successful live result demonstrates this one disclosed product contract
once; it is not a success-rate estimate or evidence of superiority over a baseline.

## Scoped repair and receipts

The broker accepts optional `repair` context with candidate/evidence hashes,
verifier attempt ID, revision/input/suite/policy bindings, bounded checks and the
previous three-file candidate. The worker fetches that candidate under its new
lease and verifies its content hash. The adapter rejects mismatched bindings and
all-passing feedback. Instructions treat diagnostics and candidate content as
untrusted data. A new independent verification is mandatory.

Usage includes `generations`: runtime model run IDs, Gateway generation IDs when
provided, and finish reasons. Missing IDs are explicit nulls; no receipt is
fabricated. `costUsd` comes from Gateway metadata. The IDs permit a separate
read-only Gateway generation lookup; event cost and actual account debit must not
be conflated.

The worker preflights the complete serialized request against 128 KiB before
spawning the adapter. Oversized repair inputs fail with known zero cost; candidate
files are never truncated. The live harness rebuilds the adapter from current
source before enabling its model service and rejects source changes during build.

## Runtime retirement evidence

Private eve sessions otherwise default to deleting their history on completion.
GraphOS explicitly uses `experimental.workflow.retention: "default"` so its
private Workflow store retains completion and usage evidence. The actual retention
period follows the World configuration; production retention and cleanup policy
remain operational work, and transcript files must stay private.

In eve 0.91, end-receipt reads use a non-following stream and can finish before
settlement. The broker polls retained snapshots within its existing deadline for
both the exact end delivery's applied receipt and its matching completed
`session.ended` event. Neither HTTP409 nor HTTP410 is treated as successful cleanup.
The offline runtime test exercises immediate retirement observation and a wrong-ID
rejection without model credentials.
