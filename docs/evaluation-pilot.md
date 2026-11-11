# Three-profile disclosed-contract pilot

`scripts/evaluate_profiles.py` separates **grader calibration** from **live model
performance**. The protocol is frozen in `evals/pilot-protocol.json` and embedded
in every report. This extends the milestone's evidence beyond the original task
list without implying arbitrary application support or production certification.

The three strata are `static-web` (tasks), `local-notes` (notes), and
`local-inventory` (inventory). All are small, offline browser applications with
explicit contracts, localStorage persistence, and a network-isolated Chromium
verifier. They are different product workflows within one technical family;
they do not represent games, platform bots, analytical pipelines, media, trading,
multiuser backends, or long-lived production services.

## 1. Calibrate the grader before paying for generation

```sh
python scripts/evaluate_profiles.py calibrate
```

This makes no model requests. It runs the known fixture and four altered copies
for each profile: missing HTML entrypoint, disabled storage writes, and low
contrast text, and an always-visible outline that does not distinguish keyboard
focus. The original fixture remains untouched. A negative control counts
only when the expected check fails; a missing Docker image or unrelated exception
does not count as detecting the injected defect. Positive and negative controls
are both retained, with profile, suite, policy, source, and verifier identities.

These checks measure sensitivity to specific injected faults, not grader
completeness. They cannot prove full accessibility conformance, detect every
defect, or establish model success. The report keeps all failed and errored cases.
The trusted verifier image and its configured immutable digest are prerequisites.

## 2. Run the bounded live pilot after reconciliation

First reconcile *all* prior model calls in this authorized session against the
Gateway and ledger, including failed calls. Round the total up to whole
microdollars. The operator must confirm remaining Gateway key headroom separately;
the key's soft cap is not a hard invoice ceiling.

```sh
# Set this to the newly reconciled session total, never a stale example value.
python scripts/evaluate_profiles.py live --execute \
  --prior-spend-microdollars "$GRAPHOS_RECONCILED_SESSION_SPEND" \
  --budget 2000000 --trials 2
```

The default plan has six trials: each of the three profiles once, then each again.
`--profiles static-web local-notes` selects a subset; `--trials` controls repeats
per profile. Results always identify the actual planned set. Each trial gets a
new ledger run, one generation attempt, and independent verification. There is no
repair or replacement of a failed trial. The model sees the acceptance contract,
so this is a **disclosed-contract pilot**, not a held-out evaluation.

The $2 pilot cap is an accounting allocation, not an expected price. Dispatch
requires $1 reservation headroom after prior settled pilot costs and within the
remaining $5 session authorization. Settled costs replace reservations. Unknown
costs retain at least the reservation and stop the entire pilot. A ledger cost
overrun also stops dispatch. The harness reuses the existing bounded live server,
credential isolation, sanitized provenance, and trusted verifier. It does not
export releases or deploy applications.

Only one live harness may run at a time. The prior-spend argument is an explicit
operator attestation; it cannot detect concurrent external Gateway consumers or
independently prove the accuracy of that number. Do not start this alongside
`live_acceptance.py`, repair generation, or another pilot. This tool has no
automatic resume or reconciliation command. After interruption, preserve its
report and reconcile the recorded run and provider costs before making a new
explicit dispatch decision. Stopping the process does not prove provider
cancellation. Output paths cannot overwrite previous evidence.

## 3. Interpret the report conservatively

Every dispatched trial stays in the completion denominator, including generation,
verification, infrastructure, and uncertain-accounting failures. Undispatched
trials are counted separately against the planned sample. Aggregate and per-profile
counts retain repeated failures rather than reporting only successful artifacts.
Observed fractions describe these exact trials; the sample is too small and the
tasks too related for a general reliability estimate. Source changes invalidate
the complete-run status and stop further paid dispatch when detected.

Inspect failed checks and their bound evidence before attributing a failure to the
model. A fixture-calibration pass and a successful live generation answer different
questions. Neither authorizes a claim of universal production readiness, human
team superiority, long-term reliability, or profitable trading.

The next evaluation milestone remains the broader protocol in
`evals/protocol.json`: independently curated task families with project-level
development/validation/untouched-release splits; multiple trials; paired model
or orchestration configurations on the same tasks; equal declared cost and
runtime budgets; randomized execution order; frozen independent graders; and
all failed runs included. Predeclare the decision rule before examining held-out
results. This pilot supplies operational evidence and identifies defects in that
evaluation machinery; it does not replace that future study.
