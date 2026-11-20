# ClaimSense AI: success criteria

Milestone 1, item 3 · four quantified criteria, each with how it is measured and the result at
handover. Measured on the 150-case evaluation run on Claude, 19 Nov 2026
(`docs/ClaimSense-AI-Golden-Run-2026-11-19.md`), unless stated otherwise.

| # | Criterion | Target | How it is measured | Result at handover |
|---|---|---|---|---|
| 1 | Decision accuracy | ≥ 90% of drafts give the expected outcome; holdout ≥ 80% | The 77 cases with an expected outcome (20 baseline, 52 variation, 5 holdout claims never used for tuning) | **75/77 (97%)** in the full run; the two misses were case errors, fixed and rerun: **77/77**. Holdout **5/5** |
| 2 | Pipeline latency | p95 < 60 s from the start of an assessment to the draft note written | `seconds` per run in the results file, on the runs that wrote a note | **p95 24.9 s**, median 19.2 s, slowest 47.6 s (116 runs). On AgentCore, the smoke-test dry run took 33.8 s |
| 3 | Adjuster confirmation rate | ≥ 80% of drafts confirmed without change | Confirmations ÷ reviews in `claims_mgmt.note_reviews`, over the 60 days after acceptance (the same count as the outcome bonus, SOW §6) | **Not yet measurable**: no adjuster has reviewed real work. The 8 reviews in the system are test and drill reviews. Leading indicator: 107 of 116 drafts (92%) were the model's own and passed every code check |
| 4 | Fraud routing accuracy | Recall 100% (no claim the rules flag is missed); precision ≥ 90% | FLAG outcomes against the expected outcome on the same 77 cases (with the loss-location check on) | **Recall 29/29 (100%)**. Precision **31/33 (94%)** in the full run; the 2 wrong flags were the case errors above, so 100% after the fix |

## Notes

* Criterion 1 is also the release gate: CI fails the build below 90% on the mock agents, and the
  run on Claude is the release evidence (SOW §3, "Decision on any claim").
* Criterion 3 depends on the pilot running with real adjusters; it cannot be measured on synthetic
  claims reviewed by the engineer. It is reported from the audit log, so no extra tooling is
  needed.
* Criterion 4: FLAG is the outcome that refers a claim to the fraud investigator. 4 of the 33 flags
  were on cases where the expected outcome allows either APPROVE or FLAG (two holdout claims and
  the two fixed cases).
* Targets were set at handover from the brief and the SOW, because no targets had been agreed in
  week 1.
