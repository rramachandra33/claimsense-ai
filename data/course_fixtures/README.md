# Course fixtures (core dataset)

The course-supplied synthetic data for ClaimSense. **Option 1 decision (2026-10-26):** this is the core dataset for the three client systems; the earlier generated data in `data/synthetic/` is kept only until the evaluation suite has been rebuilt from these fixtures.

## Layout

| Path | What it is |
|---|---|
| `source/` | Copied unchanged from the Week 14 session pack (`IK-Sessions/Week-14/session_pack`): 3 CSV tables, 74 claim document PDFs, 15 declarations pages, `index.csv`, and the 12-clause AutoSure Policy Manual |
| `claims.json` | Claims management: 20 claims, typed (Yes/No → bool, money and counts → numbers) |
| `policies.json` | Policy administration: 15 policies, typed (`N/A` deductible → null). Holder names are kept here as the system of record and must never leave the mock system |
| `documents.json` | Document store: 74 documents with `ocr_text` extracted from the PDF. `ocr_text` is **null for the 10 Pending documents**, even though their PDFs contain text (CLS-DOC-009) |
| `policy_clauses.json` | Retrieval corpus: the 12 clauses CLS-COLL-001 … CLS-PAY-012, parsed from the manual |
| `facts.json` | Code-computed facts per claim, using only rules stated in the manual (each fact names its clause) |
| `IMPORT_REPORT.md` | Invariant checks and a facts table for all 20 claims |

Regenerate with `python3 scripts/import_course_fixtures.py` (needs `pdftotext` from poppler). The output is deterministic.

## Rules used for facts (all from the manual)

- In force: `policy_start ≤ incident_date ≤ policy_end`, inclusive; status fields are ignored (CLS-PER-006).
- Liability Only: no own-vehicle cover (CLS-LIAB-003).
- Loss category and deductible: comprehensive for theft, vandalism, fire, flood, falling objects, glass and animal strikes; pothole is collision (CLS-COMP-002, CLS-DED-004). An unmapped incident type gives no category and no deductible.
- Net payable if covered: `max(min(estimate, ACV) − deductible, 0)` (CLS-COLL-001).
- Total-loss candidate: estimate ≥ 75% of ACV (CLS-TL-005).
- Senior confirmation: net payable above $25,000 (CLS-PAY-012).
- Document checks: pending OCR (CLS-DOC-009), medical report on a no-injury claim (CLS-INJ-008).

No decision outcome is computed here: decision codes and their order are open question 2.

## Not decided yet

- Users, groups and the entitlement rule (open question 8). The data names five adjusters: alice, bob, carol, david, eve.
- How the 150 evaluation cases are rebuilt from these 20 claims (open questions 2 and 7).
