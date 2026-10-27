"use server";

import { revalidatePath } from "next/cache";
import { runAssessment } from "@/lib/claimsense";
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
