# Validation summary

The current milestone implements three offline contracts: task list (`static-web`
v2), local notes, and local inventory. Their expanded suites include pinned
axe-core 4.14.0 audits, keyboard operation and reachability, visible focus, and
mobile reflow. This summary separates current validation from historical reports;
none of these results establishes universal platform reliability.

## Current milestone status

The expanded mandatory gate passed at `c5e4ff2`, covering platform and
functional/accessibility suites across all three profiles; calibration observed
all 12 expected outcomes. Two separate live cohorts then remained incomplete:
the first accepted zero of three dispatched trials, the second zero of two.
Their costs are reconciled, with no uncertain attempts remaining. The latest
usage/output repair passes 34 adapter tests, typecheck and credential-free runtime
smoke and the full Python/platform gate. The third cohort completed all six
trials with one accepted local-notes candidate and five failures. Its source
remained unchanged and all costs settled; the accepted release was exported.
Independent desktop/mobile review found no blocking visual defect in that notes
artifact. Separate task-list and inventory runs each exhausted two attempts
without acceptance. Fixture and regression passes do not measure model generation success.

| Check | Observed state | Evidence and scope |
|---|---|---|
| Expanded Python/platform suite | PASS at `c5e4ff2`: 245 tests plus 18 subtests (263 JUnit entries); 25 reference tests; Ruff passed | [Gate record](../evals/results/checks.json); zero failures, errors or skips, unchanged source; approximately 267 seconds; no model calls |
| HTTP/PostgreSQL/Docker acceptance | All eight cases passed | [Acceptance record](../evals/results/pytest-acceptance.json); fixture integration evidence, not model performance |
| Agent adapter | Latest repair: 34 Node tests, typecheck, build, compiled-runtime smoke and full Python/platform gate passed | [Current runtime record](../evals/results/eve-runtime-structured-reply-20261107.json); failure usage recovered only after confirmed retirement; no model calls in these checks |
| Focused inventory regression | Four inventory tests passed after the fixture correction | Followed by the completed full gate above |
| Grader calibration | PASS: 12 of 12 expected outcomes | [Calibration record](../evals/results/profile-calibration-20261107.json); conforming fixtures and missing-entrypoint, disabled-persistence and low-contrast injections for each profile; no model calls |
| Historical artifact revalidation | REJECTED by four expanded checks | [Revalidation record](../evals/results/historical-app-accessibility-revalidation-20261107.json); actual v1 candidate failed populated/completed contrast, focus width and mobile reflow; historical evidence preserved |
| First live pilot | INCOMPLETE: six planned, three dispatched, zero accepted, three undispatched | [Pilot results](profile-pilot-results.md); two verification rejections and one runtime/accounting interruption; no exports; costs later reconciled without changing outcomes |
| Second live pilot after transport repair | INCOMPLETE: six planned, two dispatched, zero accepted, four undispatched | [Separate cohort record](../evals/results/profile-live-pilot-reconnect-20261107.json); task-list reflow rejection and notes output-schema rejection, costs later reconciled |
| Third live cohort | Completed, overall FAIL: six dispatched, one accepted, five failed, none undispatched | [Source-bound report](../evals/results/profile-live-pilot-structured-20261107.json); source unchanged, all costs settled; separate from earlier cohorts |
| Current delivery | Accepted local-notes candidate exported; desktop/mobile visual spotcheck found no blocking defect | [Delivery record](../evals/results/profile-structured-pilot-deliveries-20261107.json), [visual review](profile-visual-review.json), [desktop](screenshots/profile-local-notes-desktop.jpg), [mobile](screenshots/profile-local-notes-mobile.jpg); finite review, not comprehensive accessibility certification |
| Exploratory build/repair runs | Both FAIL/EXHAUSTED after two attempts, all costs known, no exports | [Task list](../evals/results/repair-followup-static-web-20261107.json): partial repair still failed focus; [inventory](../evals/results/repair-followup-local-inventory-20261107.json): identical candidate rejected again; do not alter the one-of-six pilot result |
| CI at `c5e4ff2` | Both workflows passed | [CI run 42411292679](https://github.com/MichalKuderski/GraphOS/actions/runs/42411292679) and [CI run 42411288496](https://github.com/MichalKuderski/GraphOS/actions/runs/42411288496) |
| CI at `5bc88bed` | Both workflows passed | [CI run 42407531808](https://github.com/MichalKuderski/GraphOS/actions/runs/42407531808) and [CI run 42407528156](https://github.com/MichalKuderski/GraphOS/actions/runs/42407528156); do not apply these passes to the later transport repair |

The current full local gate at `c5e4ff2` records source digest
`feb503899c9eaab24d236f4848a41eb7b433a59413a72041eaf7e57ab90e33bf`.
The earlier local gate for transport repair `801f711` records source digest
`4f782c50dd042b71c01f0adad72bbb16c3c32d8ae85c831ffa1487f7f1f7aecc`.
The earlier expanded gate, calibration and first pilot ran on `5bc88bed` with digest
`4bf02598a45ba6903a92133f0a311006fc77ebbfa86b15ed5fd293723d3e7ff4`.
The source digest covers Python/runtime assets, profiles,
verifier assets, scripts, tests, eve source/instructions, and dependency locks.
It also checks that source remained unchanged. Candidate evidence additionally
binds the exact profile suite, sandbox policy, immutable verifier image, input,
and candidate artifact. Updating the trusted asset tree or profile cannot reuse
the earlier suite's evidence. Test and subtest counts are finite checks, not
independent product trials or estimates of uptime.

The pilot exposed a 60-second HTTP stream lease while client reconnection was
disabled. The subsequent repair performs bounded GET-only reconnection to the
same delivery/cursor under the original deadline, without resubmitting generation.
Its three new real HTTP/client tests brought that revision to 25 passing tests.
Typecheck, a fresh build and credential-free runtime smoke also passed at
`801f711`; the full platform gate also passed. The
[interruption record](../evals/results/profile-pilot-interruption-20261107.json)
preserves the timeline, original unknown-cost hold, both recovered receipts and
subsequent reconciliation to 24,126 microdollars with no remaining reservation
or uncertain attempt.
This repairs the diagnosed stream behavior; it neither recovers missing billing
evidence by itself nor proves a successful post-repair live run. The receipt
lookup and operator reconciliation resolved the accounting hold before the new
second live experiment began.

The second cohort exposed a separate failed-output accounting gap. The notes
model completed one charged call but returned `OUTPUT_SCHEMA_NOT_FULFILLED`;
the broker rejected the turn before retaining its complete usage. The
[reconciliation record](../evals/results/profile-schema-rejection-reconciliation-20261107.json)
binds the single $0.008832 provider receipt, confirmed retirement and operator
reconciliation. The attempt is terminal `EXHAUSTED`, with no reservation or
uncertain cost. The latest repair preserves validated failure usage only after
retirement and forces the exact `eve__reply` operation. Revised instructions
address the observed UI defects; this is development against disclosed contracts,
not held-out evaluation. The updated 34-test adapter suite, typecheck and
credential-free runtime smoke and full platform validation passed at `c5e4ff2`.
Generation IDs and failed-call receipt identities are not yet durably committed
to the ledger before the worker's final report. A crash in that earlier window
can still require external receipt recovery; terminal usage recovery does not
establish complete recovery from worker or service failures.

The [second-cohort receipts](../evals/results/profile-reconnect-pilot-receipts-20261107.json)
total $0.03348760. The refreshed cumulative provider-receipt sum and key spend
both equal **$0.14852750** before any further cohort. The $1 soft budget remains
active and unchanged. This is a dated reconciliation point, not a future balance.

The completed third cohort then incurred **$0.13305905** across
[17 independently fetched provider receipts](../evals/results/profile-structured-pilot-receipts-20261107.json).
Cumulative receipt-backed spending is **$0.28158655** before exploratory runs.
The initially observed aggregate key-budget reading was lower; it must not be
claimed equal to or substituted for the receipt total. All six trial costs are
settled, including the two failed builds that retained their known usage.

[Retained output diagnosis](../evals/results/profile-structured-output-diagnosis-20261107.json)
shows that the first task-list trial selected the forced reply tool, but supplied
empty file strings and then an extra top-level property. Strict schema checks
rejected these arguments and the existing three-model-call limit ended the turn.
The schema was not weakened and no candidate was delivered. Other third-cohort
rejections covered focus contrast, mobile quantity-label overflow, inventory text
contrast, and a second pre-verification runtime failure with known usage.

The separate task-list follow-up corrected empty-list ARIA and mobile reflow
after one repair but still failed the minimum focus-outline width. A checkbox
styling omission is a hypothesis, not a browser-confirmed diagnosis. Inventory's
repair returned the exact same candidate digest,
`3854b44d4b1eb92caacc838ba3290581d0fa657905aefc7d4e21fb05b90ae6c4`;
distinct verification attempts rejected its populated Save-button contrast and
long quantity/status text overflow again. Neither follow-up earned a release.

The [task-list receipts](../evals/results/repair-followup-static-web-receipts-20261107.json)
total $0.03437364 and the [inventory receipts](../evals/results/repair-followup-local-inventory-receipts-20261107.json)
total $0.03130749. The [final ledger/spend review](../evals/results/final-spend-ledger-review-20261107.json)
records **$0.34726768** cumulative receipt-backed spend, with zero reservations
and uncertain attempts across all 13 dispatched runs. The fresh aggregate budget
reading was $0.34044667, lower by $0.00682101—the exact amount of a known receipt.
The cause of that discrepancy is not established. Use the higher receipt basis;
do not claim invoice reconciliation or aggregate equality. The $1 non-resetting
soft budget and $5 session authorization remain unchanged.

## Retained failures and repairs in this milestone

The [first expanded full run](../evals/results/expanded-before-fixture-repair-20261107.json)
failed: 228 tests passed and one inventory test failed. The inventory fixture's
decorative `aria-hidden` glyph caused an incomplete axe contrast finding. The
fixture was corrected by removing that glyph; the verifier still fails both
violations and incomplete findings. This was a fixture change, not a weakened
acceptance threshold. Focused inventory checks and the subsequent full mandatory
run passed; the original failed result remains available.

The shared control checks also distinguish programmatic `tabindex=-1` elements
from native interactive controls. Native controls remain within keyboard and
focus checks. Regression cases were added for that boundary; their inclusion in
the full suite does not amount to a complete manual accessibility audit.

An earlier expanded-suite attempt hit
[local storage exhaustion](../evals/results/accessibility-storage-exhaustion-20261107.json)
during concurrent Docker verifier creation. The VFS driver created full copies
and left unreferenced partial layers. Its failed cases remain recorded and were
not treated as expected defect detection.

[The accessibility-milestone recovery record](storage-recovery-accessibility.json)
documents the user's explicit approval for four identified orphan layer pairs,
fresh Docker-reference checks, targeted cleanup, preservation of database
volumes, and rebuilding the verifier. The replacement image identity is
`sha256:5e41aa97d58442daf1d05e49bf2ccc7b63d382e954a8befac26ad4d72b7f9e29`.
Local VFS browser checks now run serially. Production disk admission, workload
scheduling, and automatic storage recovery remain open operating requirements.

## Historical measured results

The earlier single-profile milestone remains available in
[its source revision](https://github.com/MichalKuderski/GraphOS/blob/220c96f/docs/validation-summary.md).
Its 148 Python tests and 18 subtests, 25 reference tests, and 20 adapter tests
were measurements of that revision. These counts and passes are not rebound to
the current expanded source.

| Earlier observation | Measured result | Retained evidence |
|---|---|---|
| Genuine model build | Task-list v1 candidate passed eight checks and exported a release | [Initial live result](../evals/results/live-20261107T185333-be67cfb4.json) |
| Controlled model repair | Declared persistence fault rejected; one live repair earned fresh eight-check evidence | [Controlled-repair result](../evals/results/controlled-repair-b1f44a1b1f0a4a3ba472194c5919a3cc.json) |
| Adapter lifecycle | Compilation, authenticated runtime and retirement-receipt checks | [Historical adapter record](agent-validation-update.json) |
| Dashboard | Backend creation, revision, cancellation, release download, responsive behavior and credential checks | [Dashboard record](dashboard-validation.json) |
| CLI delivery | Manifest/candidate identities verified and atomic export completed | [CLI record](cli-validation.json) |
| Packaged API | 18 non-root/read-only service checks passed | [Container record](container-validation.json), including its exact image/source identities and later-change exclusions |
| Local restore | Ten tables, 18 CAS objects and four release manifests validated | [Restore record](restore-validation.json); local-cluster drill, not production recovery certification |

Earlier missing-image and disk-exhaustion failures remain under `evals/results/`.
[The first storage recovery](storage-recovery.json) records a separate, earlier
cleanup. Neither recovery proves that GraphOS can automatically repair a failed
host, and the local restore drill does not establish a remote production RPO/RTO.

At completion of the earlier live milestone, the provider-reported key total was
$0.05466171, including failed adapter attempts. Two pre-provider Gateway
rejections were reconciled to zero using their explicit responses, terminal
workflows, and matching settled usage. See [live validation](live-validation.md)
for every attempt, receipt and reconciliation basis. That number is historical;
the next live batch must reconcile cumulative spending again. The session's
authorization remains $5 and the dedicated $1 Gateway budget remains a soft cap.
No billing change is part of the current validation work.

## Interpretation and remaining evidence

The first accepted app's independent visual review found delete-button contrast
of 2.77:1 and completed-task contrast of 2.45:1. Its original eight-check suite
did not measure those defects. [Those visual findings](live-visual-review.json)
motivated the expanded gates; changing the grader does not retroactively fix or
recertify an older artifact. Revalidation of that exact artifact against v2
confirmed populated/completed contrast failures and additionally rejected focus
outline width and 320px reflow with a long label.

Calibration demonstrated acceptance of three conforming fixtures and rejection
of nine designated faults. An unrelated container error did not count as a
detected defect. Live trials answer a different question and retain generation,
verification, infrastructure and accounting failures. The incomplete pilot uses
disclosed contracts within one offline technical family. Even a completed pilot
does not establish held-out performance, a general reliability percentage, or
superiority over another orchestration design. The next milestone is better
generation and precise, control-specific repair within these contracts, plus a
minimal provider-side `strict: true` compatibility canary for the selected Gateway
route. Preserve the current graders and failed outcomes. Detect no-op repairs
when candidate/input/suite/policy bindings match before redundant verification.

The focused-state outline gate can miss always-on outlines. Add focused/unfocused
negative controls and bind a corrected suite to fresh evidence. The accepted
notes app independently showed conditional focus CSS and a distinct focused
textbox outline; this supports its finite review, not a general claim about the
grader. Early durable provider-ID capture remains open. Both incomplete pilots
and all third-cohort failures remain unchanged. See [pilot results](profile-pilot-results.md)
for the accounting observations and resolution.

Manual accessibility and product review, untouched project-level benchmarks,
matched-budget comparisons, provider/worker failures, load and soak tests,
multi-tenant authorization, stronger worker isolation and production operations
remain separate gates. Games, bots, data pipelines, media and trading research
remain non-executable contract-only profiles.

See [the roadmap](implementation-roadmap.md) for deliverables and exit evidence,
and [production readiness](production-readiness.md) for the current release and
trust boundaries.
