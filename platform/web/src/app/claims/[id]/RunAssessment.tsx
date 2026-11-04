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

const BUTTON =
  "inline-flex items-center gap-1.5 rounded-lg bg-claimsense-primary px-3 py-1.5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-claimsense-deep disabled:opacity-60";

/** Claim statuses that mean the claims system has already decided the claim. */
const DECIDED_STATUSES = ["approved", "denied", "closed", "settled", "paid"];

export function isDecided(claimStatus: string): boolean {
  return DECIDED_STATUSES.includes(claimStatus.trim().toLowerCase());
}

/**
 * The button. On a claim that is already decided, the first click only asks; the run starts
 * when the adjuster clicks Rerun in that question.
 */
function RunButton({ claimStatus, asking, onAsk, onCancel }: {
  claimStatus: string;
  asking: boolean;
  onAsk: () => void;
  onCancel: () => void;
}) {
  const { pending } = useFormStatus();
  const seconds = useElapsedSeconds(pending);

  if (pending) {
    return (
      <>
        <button type="submit" disabled className={BUTTON}>
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          Running the four agents… {seconds} s
        </button>
        <p role="status" className="text-xs font-medium text-claimsense-primary">
          A run usually takes 40–60 seconds. The new note appears below when it finishes.
        </p>
      </>
    );
  }

  if (asking) {
    return (
      <div role="alertdialog" aria-label="Rerun on a decided claim"
        className="flex flex-wrap items-center gap-3 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900 ring-1 ring-amber-200">
        <span>It is already {claimStatus.toLowerCase()}. Rerun it?</span>
        <button type="submit" className={BUTTON}>
          <Play className="h-3.5 w-3.5" />
          Rerun
        </button>
        <button type="button" onClick={onCancel}
          className="rounded-lg px-3 py-1.5 text-sm font-semibold text-amber-900 ring-1 ring-amber-300 hover:bg-amber-100">
          Cancel
        </button>
      </div>
    );
  }

  if (isDecided(claimStatus)) {
    return (
      <button type="button" onClick={onAsk} className={BUTTON}>
        <Play className="h-3.5 w-3.5" />
        Run assessment
      </button>
    );
  }

  return (
    <button type="submit" className={BUTTON}>
      <Play className="h-3.5 w-3.5" />
      Run assessment
    </button>
  );
}

/** The Run assessment button, and what the last run did. The note itself appears in the list below. */
export function RunAssessment({ claimId, claimStatus }: { claimId: string; claimStatus: string }) {
  const action = runAssessmentAction.bind(null, claimId);
  const [state, formAction] = useFormState<RunState>(action, { result: null, error: null });
  const [asking, setAsking] = useState(false);
  const result = state.result;

  // The form's action is the run itself, so the button sees it as pending (spinner and timer,
  // which replace the question while it runs). The question is closed once the run has answered.
  useEffect(() => {
    setAsking(false);
  }, [state]);

  return (
    <div className="space-y-3">
      <form action={formAction} className="flex flex-wrap items-center gap-3">
        <RunButton claimStatus={claimStatus} asking={asking}
          onAsk={() => setAsking(true)} onCancel={() => setAsking(false)} />
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
