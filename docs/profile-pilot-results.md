# Three-profile pilot results

The third cohort completed all six planned trials: **one local-notes candidate
was accepted and exported; five trials failed**. Its overall report status is
`FAIL`, all trial costs settled, and source remained unchanged. The earlier two
incomplete cohorts remain separately recorded. These are development trials on
disclosed contracts, not a general reliability estimate.

| Cohort | Planned | Dispatched | Accepted | Failed/incomplete | Undispatched |
|---|---:|---:|---:|---:|---:|
| Original expanded contracts | 6 | 3 | 0 | 3 | 3 |
| Reconnected transport | 6 | 2 | 0 | 2 | 4 |
| Typed reply and retained failure usage | 6 | 6 | 1 | 5 | 0 |

The first November 7, 2026 live pilot dispatched three of six planned trials. **No
candidate qualified for release.** Two candidates failed verification; the
inventory attempt was interrupted before verification. Its provider costs were
subsequently reconciled without changing its failed outcome. The remaining three
trials were not dispatched, and no releases were exported from this cohort.

A [second six-trial cohort](../evals/results/profile-live-pilot-reconnect-20261107.json)
ran on the repaired transport, then stopped after two dispatched trials, with
zero accepted and four undispatched. Its costs are also reconciled. The latest
usage/output repair and instructions passed full local validation. A
[third six-trial cohort](../evals/results/profile-live-pilot-structured-20261107.json)
completed with the outcome above. Results are kept separate across these changed
configurations. Independent review of the accepted notes app found no blocking
visual defect. Separate task-list and inventory build/repair runs each exhausted
two attempts without acceptance; these do not change the pilot denominators.

The [retained pilot report](../evals/results/profile-live-pilot-20261107.json)
records source digest
`4bf02598a45ba6903a92133f0a311006fc77ebbfa86b15ed5fd293723d3e7ff4`,
unchanged throughout the experiment, and the frozen
[disclosed-contract protocol](evaluation-pilot.md). Each trial allowed one build
attempt and no repair; an agent build can contain multiple model invocations.
This was neither a held-out benchmark nor a comparison with another agent design.

## First-cohort outcomes

| Profile | First trial | Second trial |
|---|---|---|
| Task list (`static-web` v2) | Rejected: populated/completed text contrast, focus-outline contrast, and horizontal overflow with a long task label at 320px | Not dispatched |
| Local notes | Rejected: required accessible structure/search behavior, missing-field explanation, literal-input journey, focus contrast, and mobile reflow | Not dispatched |
| Local inventory | Runtime interruption before verification; originally `RECONCILIATION_REQUIRED`/`UNKNOWN`, later reconciled to 24,126 microdollars and terminal `EXHAUSTED` | Not dispatched |

These are zero accepted candidates out of three dispatched trials. The three
undispatched trials are separately retained against the six-trial plan. This
small, interrupted sample does not estimate general model reliability. In
particular, the inventory trial is not evidence of a product-level defect because
its candidate never reached independent verification.

Before live generation, [grader calibration](../evals/results/profile-calibration-20261107.json)
produced all 12 expected outcomes: each profile's conforming fixture passed,
while missing entrypoints, disabled persistence and low contrast were rejected
by their designated checks. No model calls were needed. This measures those
specific controls, not grader completeness or generation quality.

The [actual historical task-list artifact](../evals/results/historical-app-accessibility-revalidation-20261107.json)
was also rechecked without model calls. It failed populated/completed contrast,
focus-outline width and mobile reflow under v2. Its earlier v1 acceptance is
preserved as historical evidence and does not qualify it under the expanded suite.

## Second-cohort outcomes

The second report records source digest
`4f782c50dd042b71c01f0adad72bbb16c3c32d8ae85c831ffa1487f7f1f7aecc`,
unchanged during the run, and retains its original `INCOMPLETE` status and stop
reason. It does not replace the first cohort.

| Profile | Dispatched outcome | Undispatched trials |
|---|---|---|
| Task list | Rejected by `mobile_reflow`: long delete-control text escaped the 320px viewport | One |
| Local notes | Model call completed, but `OUTPUT_SCHEMA_NOT_FULFILLED` prevented a valid candidate; the broker then lost usage at the error boundary | One |
| Local inventory | None | Two |

The notes attempt stopped before independent product verification, so it is an
output-contract/runtime failure rather than evidence about the app's behavior.
All two dispatched failures and four undispatched trials remain recorded. No
candidate was exported.

## Third-cohort outcomes

The [completed third-cohort report](../evals/results/profile-live-pilot-structured-20261107.json)
records source digest
`feb503899c9eaab24d236f4848a41eb7b433a59413a72041eaf7e57ab90e33bf`,
unchanged throughout all six trials. Each trial still allowed one build attempt
and no controller repair. Multiple internal model calls can occur within that
build, subject to the existing model-call limit.

| Trial | Outcome |
|---|---|
| Task list 1 | Rejected before browser verification: invalid reply arguments, then model-call limit; known usage retained |
| Local notes 1 | Passed its current suite; release subsequently exported |
| Local inventory 1 | Rejected: a long quantity label overflowed at 320px |
| Task list 2 | Rejected: focus-outline contrast below 3:1 |
| Local notes 2 | Runtime failure before candidate verification; known usage retained |
| Local inventory 2 | Rejected: `.eyebrow` text contrast in empty and populated states |

The [first task-list diagnosis](../evals/results/profile-structured-output-diagnosis-20261107.json)
confirms that the forced `eve__reply` tool was selected. The first call supplied
empty strings for the required files; subsequent calls added a disallowed
top-level `styles.css` property. The unchanged strict schema correctly rejected
them and the existing three-call limit stopped further generation. Forcing the
tool therefore did not guarantee valid arguments or a successful application.

The accepted notes candidate was exported through the normal release path;
the [delivery record](../evals/results/profile-structured-pilot-deliveries-20261107.json)
binds its run and manifest. Its [visual review](profile-visual-review.json) found
no blocking defect at 1280px desktop and 390px mobile widths in a populated/editing
state. The [desktop](screenshots/profile-local-notes-desktop.jpg) and
[mobile](screenshots/profile-local-notes-mobile.jpg) screenshots show wrapped
long titles and readable controls without horizontal overflow; no page errors
were captured. Conditional focus CSS and the focused title textbox were also
observed. This was not a screen-reader, zoom, alternate-browser or exhaustive
interaction review. One pass in
this six-trial cohort demonstrates one accepted artifact under this contract,
not broad reliability or improved performance relative to a controlled baseline.

Two exploratory demonstrations ran separately, each with a fresh build and one
scoped repair. Both exhausted their two-attempt limits without a release and
retained known costs. They do not replace failed pilot trials or change this
cohort's **one-of-six** result.

| Exploratory profile | Initial candidate | Repair outcome |
|---|---|---|
| [Task list](../evals/results/repair-followup-static-web-20261107.json) | Failed empty-list ARIA, focus-outline width and mobile reflow | Candidate changed; ARIA and mobile checks passed, but focus width still failed |
| [Inventory](../evals/results/repair-followup-local-inventory-20261107.json) | Failed populated Save-button contrast and long quantity/status text reflow | Exact same candidate returned; a distinct verification attempt rejected the same defects again |

Inventory's repeated candidate digest was
`3854b44d4b1eb92caacc838ba3290581d0fa657905aefc7d4e21fb05b90ae6c4`.
This was a no-op model repair, not a successful correction. A checkbox-specific
CSS omission may explain the task-list focus failure, but that cause has not
been confirmed in the browser and is not reported as established.

## Runtime diagnoses and repairs

The [interruption investigation](../evals/results/profile-pilot-interruption-20261107.json)
traced the inventory interruption to the HTTP stream's 60-second lease while
the installed client's reconnection option was disabled. This was a stream
termination, not expiration of the overall agent deadline. The adapter repair
reopens only the GET stream for the same delivery and event cursor, within a
bounded reconnect count and the original deadline. It does not resend the model
request or silently start a replacement build.

Three new tests exercise the real HTTP/client path; the adapter suite now has
25 passing tests. At repair commit `801f711`, typecheck, a fresh build and a
credential-free compiled-runtime smoke test also passed with zero model calls.
The full platform gate also passed: 233 Python tests plus 18 subtests, 25 reference
tests and Ruff, with zero failures, errors or skips and unchanged source digest
`4f782c50dd042b71c01f0adad72bbb16c3c32d8ae85c831ffa1487f7f1f7aecc`.
The second live cohort began only after cost reconciliation. These passes apply
to that transport revision, not automatically to the subsequent usage/output repair.

The second cohort exposed a different accounting defect: complete charged usage
existed for the schema-rejected notes turn, but the broker error path discarded
it. The latest implementation recovers usage only after confirmed retirement
and completion checks, validates the failure payload, and forwards it through
the Python adapter. The model is required to use the exact runtime `eve__reply`
tool for the typed output. None of these accounting steps turns a failed output
into an accepted artifact.

The updated adapter has 34 passing tests, plus passing typecheck and
credential-free runtime smoke. The full gate passed at `c5e4ff2`: 245 Python tests
plus 18 subtests (263 JUnit entries), 25 reference tests and Ruff, with zero
failures, errors or skips and unchanged source digest
`feb503899c9eaab24d236f4848a41eb7b433a59413a72041eaf7e57ab90e33bf`.
The third cohort began with 148,528 microdollars of prior spend, a 2,000,000-microdollar
pilot allocation and the existing 5,000,000-microdollar session authorization.
All six trials completed and their receipt lookup is recorded below.
Instructions also now address observed accessible roles,
field validation, focus contrast and text wrapping. Because these instructions
were adjusted using the trial failures, later outcomes are development evidence
on disclosed contracts, not untouched holdout performance.

## Accounting reconciliation

The explicitly **PARTIAL** [provider receipt report for the task and notes trials](../evals/results/profile-pilot-receipts-20261107.json)
contains four receipts totaling **$0.03625219**. The ledger conservatively rounded the two settled trials
to 36,254 microdollars. Combined with the earlier reconciled $0.05466171, those
four receipts establish a $0.09091390 cumulative subtotal before inventory.

A subsequent [read-only Gateway observation and inventory receipt](../evals/results/profile-pilot-interruption-20261107.json)
reported **$0.11503990** total key
spend. The first inventory generation,
`gen_01M6VS42WHV87N6GFATKJV15SY`, has a known $0.012862 charge. The second inventory
generation, `gen_01M6VS5682CGZNX4SV7PG0ZQGD`, was identified by the user from the
Gateway log and independently verified through `GET /v1/generation`. Its exact
charge was $0.011264, with matching model, tokens and timing. The two receipts
therefore establish the interrupted attempt's **$0.024126** cost. The earlier
aggregate difference was only corroboration; it was not used as a substitute
for those receipts.

The original **1,000,000-microdollar ($1) accounting hold** remained until that
verification. The operator reconciliation API replaced it with 24,126
microdollars, an adjustment of -975,874 microdollars. The final ledger state is
`EXHAUSTED`, with zero reserved microdollars and zero uncertain attempts. This
does not revive the failed trial or grant it an accepted candidate.

No additional generation occurred between the stop and reconciliation. The
reconciled cumulative provider total before the new cohort was **$0.11503990**;
the new experiment conservatively admitted 115,040 microdollars as prior spend.
This was the second cohort's starting balance, not the latest session total. The
dedicated $1 Gateway budget remains a soft cap and the session authorization
remains $5. No billing settings, credit purchases or top-ups changed.

The [interruption record](../evals/results/profile-pilot-interruption-20261107.json)
preserves both receipts, the original hold, the failed local recovery search and
the operator API result. The original live report remains `INCOMPLETE` and links
to that subsequent reconciliation; its outcomes and original stop reason remain.

For the second cohort's notes attempt, the
[schema-rejection reconciliation](../evals/results/profile-schema-rejection-reconciliation-20261107.json)
matched generation `gen_01M6VT2YX8QTTHN6CV3SYFXD6Y` to one completed model call and
confirmed session retirement. Its exact $0.008832 charge replaced the $1 hold
through the operator API. The final state is `EXHAUSTED`, with zero reservation
and zero uncertain attempts; no model calls were made for reconciliation.

All four [second-cohort provider receipts](../evals/results/profile-reconnect-pilot-receipts-20261107.json)
sum to **$0.03348760**. The refreshed all-session receipt sum and Gateway key
spend both equal **$0.14852750** before any further cohort. Both cohorts' costs
are therefore reconciled. The dedicated $1 non-resetting soft budget remains
active and unchanged; the $5 session authorization also remains unchanged.
These figures are the pre-third-cohort reconciliation point, not a future balance.

The [third-cohort receipt report](../evals/results/profile-structured-pilot-receipts-20261107.json)
contains **17 receipts totaling $0.13305905**, including the failed builds.
The ledger conservatively rounded this to 133,066 microdollars. Cumulative
receipt-backed session spending is **$0.28158655** before the exploratory runs.
All six trial costs are settled, with no uncertain attempts. The initial
aggregate key-budget observation was $0.27476554, lower by $0.00682101; that
reading was not claimed equal to the authoritative receipt sum.

The [task-list follow-up receipts](../evals/results/repair-followup-static-web-receipts-20261107.json)
add **$0.03437364** and the [inventory follow-up receipts](../evals/results/repair-followup-local-inventory-receipts-20261107.json)
add **$0.03130749**. The [final spend/ledger review](../evals/results/final-spend-ledger-review-20261107.json)
records 26 new receipts after the earlier $0.14852750, for **$0.34726768 cumulative
receipt-backed session spending**. All 13 dispatched runs across the three
cohorts and two exploratory follow-ups have zero reserved cost and zero uncertain
attempts. No further model calls are planned for this milestone.

The fresh budget aggregate was **$0.34044667**, $0.00682101 below the receipt sum.
That difference equals known receipt `gen_01M6VV7NK48S8WQV3M1Q1S5TVQ`, but its
cause is not established. The higher receipt total is the conservative spending
basis; this is not a claim of invoice reconciliation or aggregate equality. The
$1 non-resetting soft budget remains active and unchanged, as does the $5 session
authorization. No billing settings, credit purchases or top-ups changed.

## Exit evidence

Receipt/ledger reconciliation and local validation of the transport and
usage/output repairs are complete. The accepted notes artifact has both current
suite evidence and a finite visual spotcheck. Retain the completed third cohort
separately from both incomplete runs and unsuccessful exploratory repairs.

The next milestone is generation quality and precise repair within the existing
contracts. Diagnostics should identify the exact control, state and computed
style. Test provider-side `strict: true` compatibility with a minimal canary on
the selected Gateway/model route before relying on it. Detect unchanged repair
candidates with matching input/suite/policy bindings before redundant verification.
Do not weaken current graders or replace failed observations.

The focus gate also needs a focused/unfocused negative control: checking only a
focused outline can miss an always-on outline. A corrected suite must earn fresh
evidence bindings. The accepted notes artifact independently used conditional
focus selectors and showed a distinct focused textbox, so its finite review
stands; it does not prove grader completeness. Persist Gateway generation IDs
and failed-call receipt identities before the worker's final report reaches the
ledger; this earlier crash window remains open despite terminal usage recovery.

Untouched benchmarks, matched-budget comparisons, manual accessibility testing,
provider/worker fault tests, load/soak operation, production recovery and tenant
isolation remain additional milestones. These results do not establish universal
production reliability, full WCAG conformance, or readiness for games, bots,
data pipelines, media or trading execution.
