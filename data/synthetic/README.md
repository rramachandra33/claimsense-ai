# ClaimSense AI synthetic data

All records are **synthetic**. No real people, policies or claims appear anywhere. Regenerate with:

```bash
python3 scripts/generate_synthetic_data.py   # deterministic: same seed, byte-identical output
```

## Files: the three client systems plus supporting data

| File | Client system | Contents |
|---|---|---|
| `policies.json` | Policy administration | 147 policies: term, events (cancellation, reinstatement, coverage change), premium due, vehicles, drivers, excluded drivers, coverages and deductibles, endorsements, and a **`status_field` that is sometimes stale on purpose** |
| `claims.json` | Claims management | 146 claims: loss time (ISO with offset; one recorded in UTC), loss type, coverage claimed, driver, FNOL narrative, injuries, witnesses, structured repair estimate, ACV valuation, rental/towing, `legacy_fraud_score`, and `third_parties` (see below) |
| `documents.json` | Document store | 394 documents: FNOL, police reports, estimates, photo logs, medical notes, emails, app/telematics/weather records. Each has an `author_role`, so a "claimant" document titled "Adjuster note" is still claimant-authored |
| `claim_history.json` | Claims history | 16 prior closed claims, joined by `party_id` / `policy_id` / `vin`, **never by name** |
| `policy_clauses.json` | Retrieval corpus | 36 policy clauses (`CLS-*`) and 10 claims-handling guidelines (`GDL-*`), the citation targets |
| `users.json` | Identity | 11 users (adjusters, senior, SIU, supervisor, auditor, a suspended user, a service account) and the access rule |
| `claim_labels.json` | Answer key | The expected outcome for every claim (acceptance criterion 1: any claim returns a decision) |

## Decision outcomes

`APPROVE` · `DENY` · `FLAG` (refer to Special Investigations) · `ROUTE` (with `route_to`: `total_loss`, `injury`, `large_loss`, `litigation`, `liability`, `coverage_review`, `document_request`). A refused request returns **no outcome and no claim data**.

Precedence when several apply: **DENY > FLAG > ROUTE > APPROVE**. Two exceptions: a loss that is not in force is denied even if it also looks suspicious, and fraud referral takes precedence over injury or litigation routing.

## What is code and what is the model

`evals/cases.jsonl` contains, for every granted case, the `deterministic_facts` that **code** must compute exactly. `compute_facts()` in the generator is the reference implementation.

- **Dates:** the policy period runs from 12:01 a.m. on the start date to 12:01 a.m. on the end date, in the region's *standard* time (NORTH/EAST −05:00, SOUTH −06:00, WEST −08:00). Cancellation, reinstatement gaps and the 10-day premium grace period are all computed here. `in_force_at_loss` comes from code; `status_field` is never trusted.
- **Money:** deductible (waived for glass *repair*); total loss if `repair ≥ 0.75 × ACV` (inclusive) or the vehicle is unrecovered after theft; rental capped at $40/day for 30 days; towing capped at $150; unpaid grace-period premium deducted. If there is no structured estimate there is no payout: the model never lifts figures from free text.
- **Authority:** adjuster $15k, senior $50k, supervisor $100k (`exceeds_assigned_authority`).
- **History signals:** prior-claim counts by policy and by party (36 months), and `linked_entity_hits` (for example, a witness phone number shared with other claims). These are exposed as counts, not as other claims' contents.
- **Third parties:** `third_party_count`; `third_party_recovery_candidate` (another party at fault **and** insured, so the insurer can recover what it pays); `third_party_uninsured_or_unidentified`.
- **Access:** see `users.json → access_rule`. It is enforced before any agent runs.

The **model** reads the file and decides which clause applies, whether accounts are consistent, whether wording is ambiguous, and which outcome to recommend. It cites clause IDs it actually retrieved, and a licensed adjuster confirms every result.

## Third parties

The client's policy administration system holds only its own policies, so another driver's insurer is recorded on the claim in claims management. Each claim involving another party (37 in the eval set) has `third_parties` entries with `party_role` (`other_driver`, `unidentified_driver`, `parked_vehicle_owner`, `pedestrian`), name, vehicle, plate, `insurer` and `policy_number`, `insurance_status` (`insured`, `uninsured`, `unidentified`, `not_applicable`), `at_fault` (of the *other* party: true, false or null) with `fault_source` (`police_report`, `claimant_statement`, `disputed`, `undetermined`), plus injury, property claim, occupants and attorney flags. Where a police report exists, the same details appear at the end of its text.

## Canary strings

Strings like `CNRY-I1-5TGA` appear only in "decoy" claims. If one shows up in a response about a different claim, data has leaked between records.
