"use client";

import { useState } from "react";
import { Check, Loader2, X } from "lucide-react";
import { reviewNoteAction } from "./actions";

type Decision = "confirmed" | "rejected";

/**
 * Confirm or Reject on a draft note. Choosing one opens a reason box; a rejection needs a reason,
 * and so does any review of an agent-failure DENY. The API records the review once, with who and
 * when, and audits it.
 */
export function ReviewNote({ claimId, noteId, agentFailure }: {
  claimId: string;
  noteId: number;
  agentFailure: boolean;
}) {
  const [decision, setDecision] = useState<Decision | null>(null);
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reasonRequired = decision === "rejected" || agentFailure;

  async function save() {
    if (!decision) return;
    if (reasonRequired && !reason.trim()) {
      setError("Give a reason.");
      return;
    }
    setSaving(true);
    setError(null);
    const problem = await reviewNoteAction(claimId, noteId, decision, reason.trim());
    setSaving(false);
    if (problem) {
      setError(problem);
    } else {
      setDecision(null);
      setReason("");
    }
  }

  if (!decision) {
    return (
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button type="button" onClick={() => setDecision("confirmed")}
          className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 px-3 py-1 text-xs font-semibold text-white hover:bg-emerald-700">
          <Check className="h-3.5 w-3.5" /> Confirm
        </button>
        <button type="button" onClick={() => setDecision("rejected")}
          className="inline-flex items-center gap-1 rounded-lg px-3 py-1 text-xs font-semibold text-rose-700 ring-1 ring-rose-300 hover:bg-rose-50">
          <X className="h-3.5 w-3.5" /> Reject
        </button>
        <span className="text-xs text-claimsense-muted">
          {agentFailure ? "An agent could not finish: assess the claim and give your reason." : "Your decision on this draft."}
        </span>
      </div>
    );
  }

  return (
    <div className="mt-3 space-y-2 rounded-md bg-slate-50 p-3 ring-1 ring-claimsense-line">
      <label className="block text-xs font-medium text-slate-700" htmlFor={`reason-${noteId}`}>
        {decision === "confirmed" ? "Confirm" : "Reject"} this draft. Reason{reasonRequired ? "" : " (optional)"}:
      </label>
      <textarea id={`reason-${noteId}`} value={reason} onChange={(e) => setReason(e.target.value)} rows={2}
        maxLength={1000} className="w-full rounded-md border border-claimsense-line p-2 text-sm" />
      {error ? <p className="text-xs text-rose-700">{error}</p> : null}
      <div className="flex gap-2">
        <button type="button" onClick={save} disabled={saving}
          className={`inline-flex items-center gap-1 rounded-lg px-3 py-1 text-xs font-semibold text-white disabled:opacity-60 ${decision === "confirmed" ? "bg-emerald-600 hover:bg-emerald-700" : "bg-rose-600 hover:bg-rose-700"}`}>
          {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
          {decision === "confirmed" ? "Confirm draft" : "Reject draft"}
        </button>
        <button type="button" onClick={() => { setDecision(null); setError(null); }} disabled={saving}
          className="rounded-lg px-3 py-1 text-xs font-semibold text-slate-700 ring-1 ring-slate-300 hover:bg-slate-100">
          Cancel
        </button>
      </div>
    </div>
  );
}
