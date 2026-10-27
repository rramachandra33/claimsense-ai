import Link from "next/link";
import { OutcomeBadge } from "@/components/badges";
import { Empty } from "@/components/ui";
import { formatDateTime, formatUsd } from "@/lib/format";
import type { Note } from "@/lib/types";

function ClauseLink({ id }: { id: string }) {
  return (
    <Link href={`/clauses?q=${encodeURIComponent(id)}`}
          className="rounded bg-claimsense-bg px-1.5 py-0.5 font-mono text-xs text-claimsense-primary ring-1 ring-claimsense-line hover:underline">
      {id}
    </Link>
  );
}

function SourceTag({ source }: { source: Note["decision_source"] }) {
  if (source === "deterministic_fallback") {
    return <span className="text-xs font-medium text-amber-700">decided by code: the agents&apos; draft failed a check</span>;
  }
  return <span className="text-xs text-claimsense-muted">drafted by the agents, checked by code</span>;
}

/** One draft note: the recommendation, its citations, and how it was reached. */
function NoteCard({ note }: { note: Note }) {
  const facts = note.code_facts.facts;
  const problems = note.agent_outputs.draft_problems ?? [];
  const models = Array.from(new Set(Object.values(note.models))).join(", ");

  return (
    <article className="rounded-lg border border-claimsense-line p-4">
      <header className="flex flex-wrap items-center gap-2">
        <OutcomeBadge outcome={note.outcome} />
        <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
          {note.status.replace(/_/g, " ")}
        </span>
        <SourceTag source={note.decision_source} />
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
              Precedence is provisional ({note.code_facts.provisional_precedence.join(" > ")}) until it is decided.
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
                Object.fromEntries(Object.entries(note.agent_outputs).filter(([k]) => k !== "draft_problems")),
                null, 2)}
            </pre>
            <p className="mt-2 text-[11px] text-slate-400">Brain: {models} · run {note.run_id}</p>
          </div>
        </div>
      </details>
    </article>
  );
}

export function NotesList({ notes }: { notes: Note[] }) {
  if (notes.length === 0) {
    return <Empty>No ClaimSense notes yet. Run an assessment to draft one.</Empty>;
  }
  return (
    <div className="space-y-3">
      {notes.map((n) => <NoteCard key={n.note_id} note={n} />)}
    </div>
  );
}
