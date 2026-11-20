# Confirm or reject a draft — UI → backend workflow

## Example used

1. **alice** confirms the FLAG draft on her claim **CLM-2024-1800** (from
   [run-assessment.md](run-assessment.md)).
2. **alice** rejects an **agent-failure DENY** on **CLM-2024-2165** (a run on 2026-11-05 where Bedrock
   answered "ServiceUnavailable"; code wrote an uncited DENY saying an adjuster must assess the claim).
   A reason is required for either decision on such a draft.
3. A draft on **CLM-2024-1873** (carol's claim, net payable $30,200 if covered): **carol** (fraud
   investigator) can read it but not review it, and only **bob** (senior adjuster) may confirm it,
   because it is above $25,000 (CLS-PAY-012).

Source tests: `api/tests/test_notes.py` (reviews: who may, once only, reasons, the $25,000 rule,
agent-failure drafts, agents refused).

**Important architectural note:** the note itself is **never changed**: `claims_mgmt.claim_notes` is
append-only. The review is a separate row in `claims_mgmt.note_reviews` (who, when, decision, reason),
one per note, and the note's status is read from it. Nothing is paid or closed by ClaimSense; the
review records the adjuster's decision on the draft.

---

## 1. User action in the browser

| Step | Function | File |
|---|---|---|
| Who sees the buttons | `NotesList({ notes, canReview })`: `canReview` is true only for `adjuster` and `senior-adjuster` | `platform/web/src/app/claims/[id]/page.tsx`, `NotesList.tsx` |
| Buttons | `ReviewNote({ claimId, noteId, agentFailure })`: **Confirm** or **Reject**, then a reason box | `platform/web/src/app/claims/[id]/ReviewNote.tsx` |
| Reason needed? | `reasonRequired = decision === "rejected" \|\| agentFailure`; empty → "Give a reason." (checked again by the API) | `platform/web/src/app/claims/[id]/ReviewNote.tsx` |
| Save | `save()` → server action `reviewNoteAction(claimId, noteId, decision, reason)` | `platform/web/src/app/claims/[id]/actions.ts` |

## 2. Frontend request

| Step | Function | File |
|---|---|---|
| Call the API | `reviewNote()`: `POST /api/v1/claims/{claim_id}/notes/{note_id}/review` `{"decision": "confirmed" \| "rejected", "reason": …}` with the user's token | `platform/web/src/lib/claimsense.ts` |

## 3. API route

| Step | Function | File |
|---|---|---|
| Route | `review_draft()` | `api/src/claimsense_api/main.py` |
| Caller | `require_user()`; an OBO token (an agent) → 403 "This agent is not allowed to do that." | `api/src/claimsense_api/main.py` |
| May read the claim? | `load_claim_for(user, claim_id, "review_note")` → `can_read_claim` | `api/src/claimsense_api/main.py`, `access.py` |
| The rules | `review_note(user, claim_id, note_id, review)` | `api/src/claimsense_api/notes.py` |

`review_note()` checks, in order:

| Rule | Refusal |
|---|---|
| Group is `adjuster` or `senior-adjuster` (`REVIEWER_GROUPS`) | 403 "Your role may read drafts but not confirm or reject them." (carol, eve; the batch account) |
| Decision is `confirmed` or `rejected`; reason ≤ 1,000 characters | 400 |
| The note belongs to this claim | 404 |
| A rejection has a reason | 400 `reason_required` |
| A review of an `agent_failure` draft has a reason, either way | 400 `reason_required` |
| Confirming with net payable (`code_facts.facts.net_payable_if_covered_usd`) above $25,000 needs a senior adjuster | 403 `senior_required` "only a senior adjuster may confirm this draft (CLS-PAY-012)" |
| Once per note (primary key on `note_id`) | 409 `already_reviewed` |

Then one row in `claims_mgmt.note_reviews`, and `log_audit("review_note", "allow", reason="confirmed")`
with the reason in `detail`. Every refusal is audited too.

## 4. Response and rendering

| Step | Function | File |
|---|---|---|
| Refresh | `reviewNoteAction` → `revalidatePath("/claims/{id}")`; on a refusal the API's message shows under the buttons | `platform/web/src/app/claims/[id]/actions.ts` |
| Note card | status tag Confirmed / Rejected with who, when and the reason; the buttons are gone | `platform/web/src/app/claims/[id]/NotesList.tsx` |
| Notes query | `list_notes()`: `COALESCE(r.decision, n.status)` from `note_reviews`, so the note row is never updated | `api/src/claimsense_api/main.py` |

## Who can do what

| User | Read the draft on CLM-2024-1873 | Confirm it |
|---|---|---|
| carol (fraud investigator, assigned) | yes | no: reviews only |
| bob (senior adjuster) | yes | yes |
| alice (adjuster) | no: not her claim (403) | no |
| an agent with an OBO token | no: agents may not read notes | no |

## Call chain at a glance

```text
ReviewNote (browser) → reviewNoteAction → reviewNote → POST …/notes/{note_id}/review
  → review_draft → require_user (agents: 403) → load_claim_for → can_read_claim
               → review_note: group → decision → note on this claim → reasons
                              → $25,000 senior rule → INSERT note_reviews (once)
               → log_audit
  → revalidatePath → NotesList shows Confirmed / Rejected
```
