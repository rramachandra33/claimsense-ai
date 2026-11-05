import Link from "next/link";
import { OutcomeBadge } from "@/components/badges";
import { Empty } from "@/components/ui";
import { formatCost, formatDateTime, formatUsd } from "@/lib/format";
import type { Note } from "@/lib/types";
import { ReviewNote } from "./ReviewNote";

const DECIDED_STATUSES = ["approved", "denied", "closed", "settled", "paid"];

function StatusTag({ status }: { status: string }) {
  const colour = status === "confirmed" ? "bg-emerald-100 text-emerald-800"
    : status === "rejected" ? "bg-rose-100 text-rose-800" : "bg-slate-100 text-slate-600";
  return <span className={`rounded-md px-2 py-0.5 text-xs ${colour}`}>{status.replace(/_/g, " ")}</span>;
}

// The order the pipeline runs the agents in.
const AGENT_ORDER = ["reader", "coverage", "risk", "drafter"];

function ClauseLink({ id }: { id: string }) {
  return (
    <Link href={`/clauses?q=${encodeURIComponent(id)}`}
          className="rounded bg-claimsense-bg px-1.5 py-0.5 font-mono text-xs text-claimsense-primary ring-1 ring-claimsense-line hover:underline">
      {id}
    </Link>
  );
}

function SourceTag({ source }: { source: Note["decision_source"] }) {
  if (source === "agent_failure") {
    return <span className="text-xs font-medium text-red-700">an agent could not finish: DENY until an adjuster assesses the claim</span>;
  }
  if (source === "deterministic_fallback") {
    return <span className="text-xs font-medium text-amber-700">decided by code: the agents&apos; draft failed a check</span>;
  }
  return <span className="text-xs text-claimsense-muted">drafted by the agents, checked by code</span>;
}

/** One draft note: the recommendation, its citations, and how it was reached. */
function NoteCard({ note, canReview }: { note: Note; canReview: boolean }) {
  const facts = note.code_facts.facts;
  const problems = note.agent_outputs.draft_problems ?? [];
  const models = Array.from(new Set(Object.values(note.models).map((m) => m.split("/").pop()))).join(", ");
  const usage = note.agent_outputs.usage;
  const modelUsage = usage && Object.keys(usage.agents).length > 0 ? usage : null;

  return (
    <article className="rounded-lg border border-claimsense-line p-4">
      <header className="flex flex-wrap items-center gap-2">
        <OutcomeBadge outcome={note.outcome} />
        <StatusTag status={note.status} />
        <SourceTag source={note.decision_source} />
        {note.claim_status_at_run && DECIDED_STATUSES.includes(note.claim_status_at_run.toLowerCase()) ? (
          <span className="rounded-md bg-amber-50 px-2 py-0.5 text-xs text-amber-800 ring-1 ring-amber-200">
            second opinion: claim was {note.claim_status_at_run}
          </span>
        ) : null}
        <span className="ml-auto text-xs text-claimsense-muted">
          Note {note.note_id} · {formatDateTime(note.created_at)} · for {note.on_behalf_of}
        </span>
      </header>

      <p className="mt-3 text-sm text-claimsense-ink">{note.summary}</p>
      {note.deny_reason ? (
        <p className="mt-2 text-sm text-rose-800"><span className="font-semibold">Deny reason:</span> {note.deny_reason}</p>
      ) : null}

      <div className="mt-3 flex flex-wrap items-center gap-1.5 text-xs text-claimsense-muted">
        <span>Cites</span>
        {note.cited_clauses.length ? note.cited_clauses.map((c) => <ClauseLink key={c} id={c} />) : <span>no clause</span>}
      </div>

      {note.reviewed_by ? (
        <p className={`mt-3 text-xs ${note.status === "confirmed" ? "text-emerald-800" : "text-rose-800"}`}>
          <span className="font-semibold">{note.status === "confirmed" ? "Confirmed" : "Rejected"} by {note.reviewed_by}</span>
          {note.reviewed_at ? ` · ${formatDateTime(note.reviewed_at)}` : ""}
          {note.review_reason ? ` · ${note.review_reason}` : ""}
        </p>
      ) : canReview ? (
        <ReviewNote claimId={note.claim_id} noteId={note.note_id} agentFailure={note.decision_source === "agent_failure"} />
      ) : (
        <p className="mt-3 text-xs text-claimsense-muted">Awaiting an adjuster&apos;s review. Your role may read drafts but not confirm them.</p>
      )}

      <details className="mt-3 text-sm">
        <summary className="cursor-pointer text-xs font-medium text-claimsense-primary">How this was reached</summary>
        <div className="mt-3 grid gap-4 md:grid-cols-2">
          <div>
            <h3 className="text-[11px] font-medium uppercase tracking-wide text-slate-400">Code facts</h3>
            <dl className="mt-1 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
              <dt className="text-slate-500">In force at loss</dt><dd>{facts.in_force_at_loss ? "Yes" : "No"}</dd>
              <dt className="text-slate-500">Deductible</dt><dd>{formatUsd(facts.deductible_usd)}</dd>
              <dt className="text-slate-500">Net payable if covered</dt><dd>{formatUsd(facts.net_payable_if_covered_usd)}</dd>
              <dt className="text-slate-500">Repair / ACV</dt><dd>{facts.repair_to_acv_ratio ?? "—"}</dd>
            </dl>
            <h3 className="mt-3 text-[11px] font-medium uppercase tracking-wide text-slate-400">Signals found by code</h3>
            {note.code_facts.signals.length || note.code_facts.documentation_gaps.length ? (
              <ul className="mt-1 space-y-1 text-xs">
                {note.code_facts.signals.map((s) => (
                  <li key={s.reason}><OutcomeBadge outcome={s.outcome} /> {s.reason} <span className="font-mono text-slate-400">{s.clause}</span></li>
                ))}
                {note.code_facts.documentation_gaps.map((g) => (
                  <li key={g.reason}><span className="font-semibold text-slate-600">GAP</span> {g.reason} <span className="font-mono text-slate-400">{g.clause}</span></li>
                ))}
              </ul>
            ) : (
              <p className="mt-1 text-xs text-slate-500">None.</p>
            )}
            <p className="mt-2 text-[11px] text-slate-400">
              {note.code_facts.precedence
                ? `Precedence: ${note.code_facts.precedence.join(" > ")}; the note lists the other signals.`
                : `Precedence was provisional (${(note.code_facts.provisional_precedence ?? []).join(" > ")}) when this ran.`}
            </p>
          </div>
          <div>
            {problems.length ? (
              <>
                <h3 className="text-[11px] font-medium uppercase tracking-wide text-amber-700">Why the agents&apos; draft was replaced</h3>
                <ul className="mt-1 list-disc pl-4 text-xs text-amber-900">
                  {problems.map((p) => <li key={p}>{p}</li>)}
                </ul>
              </>
            ) : null}
            <h3 className="mt-3 text-[11px] font-medium uppercase tracking-wide text-slate-400 first:mt-0">Agent outputs</h3>
            <pre className="mt-1 max-h-72 overflow-auto rounded bg-claimsense-bg p-2 font-mono text-[11px] leading-relaxed text-slate-700">
              {JSON.stringify(
                Object.fromEntries(Object.entries(note.agent_outputs).filter(([k]) => !["draft_problems", "usage"].includes(k))),
                null, 2)}
            </pre>
            {modelUsage ? (
              <>
                <h3 className="mt-3 text-[11px] font-medium uppercase tracking-wide text-slate-400">Model usage</h3>
                <table className="mt-1 w-full text-xs">
                  <thead className="text-left text-slate-500">
                    <tr><th className="py-0.5">Agent</th><th>Model</th><th className="text-right">Tokens in</th><th className="text-right">Out</th><th className="text-right">Cost</th></tr>
                  </thead>
                  <tbody className="tabular-nums">
                    {AGENT_ORDER.filter((a) => modelUsage.agents[a]).map((agent) => [agent, modelUsage.agents[agent]] as const).map(([agent, u]) => (
                      <tr key={agent}>
                        <td className="py-0.5">{agent}</td>
                        <td className="text-slate-500">{u.model.includes("haiku") ? "Haiku 4.5" : u.model.includes("sonnet") ? "Sonnet 4.5" : u.model.split("/").pop()}</td>
                        <td className="text-right">{u.input_tokens.toLocaleString()}</td>
                        <td className="text-right">{u.output_tokens.toLocaleString()}</td>
                        <td className="text-right">{formatCost(u.cost_usd)}</td>
                      </tr>
                    ))}
                    <tr className="border-t border-claimsense-line font-semibold">
                      <td className="py-0.5" colSpan={2}>Total</td>
                      <td className="text-right">{modelUsage.input_tokens.toLocaleString()}</td>
                      <td className="text-right">{modelUsage.output_tokens.toLocaleString()}</td>
                      <td className="text-right">{formatCost(modelUsage.cost_usd)}</td>
                    </tr>
                  </tbody>
                </table>
              </>
            ) : null}
            <p className="mt-2 text-[11px] text-slate-400">Brain: {models} · run {note.run_id}</p>
          </div>
        </div>
      </details>
    </article>
  );
}

/** The claim's notes. canReview: the signed-in user is an adjuster or senior adjuster (question 8);
 * the API enforces this and the $25,000 senior rule itself. */
export function NotesList({ notes, canReview }: { notes: Note[]; canReview: boolean }) {
  if (notes.length === 0) {
    return <Empty>No ClaimSense notes yet. Run an assessment to draft one.</Empty>;
  }
  return (
    <div className="space-y-3">
      {notes.map((n) => <NoteCard key={n.note_id} note={n} canReview={canReview} />)}
    </div>
  );
}
