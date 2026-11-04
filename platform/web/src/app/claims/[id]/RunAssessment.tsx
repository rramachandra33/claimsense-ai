"use client";

import { useEffect, useState } from "react";
import { useFormState, useFormStatus } from "react-dom";
import { Loader2, Play } from "lucide-react";
import { OutcomeBadge } from "@/components/badges";
import { formatCost } from "@/lib/format";
import { runAssessmentAction, type RunState } from "./actions";

/** Seconds since the run started, counting up once a second while it runs. */
function useElapsedSeconds(running: boolean): number {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (!running) return;
    setSeconds(0);
    const started = Date.now();
    const timer = setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [running]);
  return seconds;
}

function RunButton() {
  const { pending } = useFormStatus();
  const seconds = useElapsedSeconds(pending);
  return (
    <>
      <button
        type="submit"
        disabled={pending}
        className="inline-flex items-center gap-1.5 rounded-lg bg-claimsense-primary px-3 py-1.5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-claimsense-deep disabled:opacity-60"
      >
        {pending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
        {pending ? `Running the four agents… ${seconds} s` : "Run assessment"}
      </button>
      {pending ? (
        <p role="status" className="text-xs font-medium text-claimsense-primary">
          A run usually takes 40–60 seconds. The new note appears below when it finishes.
        </p>
      ) : null}
    </>
  );
}

/** The Run assessment button, and what the last run did. The note itself appears in the list below. */
export function RunAssessment({ claimId }: { claimId: string }) {
  const action = runAssessmentAction.bind(null, claimId);
  const [state, formAction] = useFormState<RunState>(action, { result: null, error: null });
  const result = state.result;

  return (
    <div className="space-y-3">
      <form action={formAction} className="flex flex-wrap items-center gap-3">
        <RunButton />
        <p className="text-xs text-claimsense-muted">
          Reader → coverage → risk → drafter, each with its own short-lived token. Code checks the draft
          and writes one note for you to confirm.
        </p>
      </form>

      {state.error ? (
        <p className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-800 ring-1 ring-rose-200">{state.error}</p>
      ) : null}

      {result && result.status === "failed" ? (
        <div className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900 ring-1 ring-amber-200">
          <div className="font-semibold">Run failed, nothing was written</div>
          <ul className="mt-1 list-disc pl-5">
            {result.problems.map((p) => <li key={p}>{p}</li>)}
          </ul>
        </div>
      ) : null}

      {result && result.status !== "failed" && result.outcome ? (
        <div className="flex flex-wrap items-center gap-2 rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-900 ring-1 ring-emerald-200">
          <OutcomeBadge outcome={result.outcome} />
          <span>
            Note {result.note_id} {result.status === "replayed" ? "already existed" : "written"} ·{" "}
            {result.decision_source === "agent_failure" ? "an agent could not finish: DENY for an adjuster to assess" : result.decision_source === "deterministic_fallback" ? "decided by code (the draft failed a check)" : `drafted by the ${result.brain} agents`} ·{" "}
            {(result.duration_ms / 1000).toFixed(1)} s
            {result.brain !== "mock" ? ` · ${formatCost(result.cost_usd)}` : ""}
          </span>
        </div>
      ) : null}
    </div>
  );
}
