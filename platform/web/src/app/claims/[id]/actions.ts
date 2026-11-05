"use server";

import { revalidatePath } from "next/cache";
import { reviewNote, runAssessment } from "@/lib/claimsense";
import type { RunResult } from "@/lib/types";

export type RunState = { result: RunResult | null; error: string | null };

/** Run the four agents on this claim, then refresh the page so the new note shows. */
export async function runAssessmentAction(claimId: string, _prev: RunState): Promise<RunState> {
  const response = await runAssessment(claimId);
  if (!response.ok) {
    return { result: null, error: response.error?.message ?? "The run could not be started." };
  }
  revalidatePath(`/claims/${claimId}`);
  return { result: response.data, error: null };
}

/** Confirm or reject one draft note, then refresh the page so its new status shows. */
export async function reviewNoteAction(
  claimId: string, noteId: number, decision: "confirmed" | "rejected", reason: string,
): Promise<string | null> {
  const response = await reviewNote(claimId, noteId, decision, reason);
  if (!response.ok) {
    return response.error?.message ?? "The review could not be saved.";
  }
  revalidatePath(`/claims/${claimId}`);
  return null;
}
