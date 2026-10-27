import { AppShell } from "@/components/AppShell";
import { ApiErrorPanel, Empty, Panel } from "@/components/ui";
import { requireSession } from "@/lib/auth";
import { apiGet } from "@/lib/claimsense";
import type { Clause } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function ClausesPage({ searchParams }: { searchParams: { q?: string } }) {
  const session = requireSession();
  const q = (searchParams.q ?? "").trim();
  const result = q.length >= 3
    ? await apiGet<{ clauses: Clause[]; count: number }>(`/api/v1/clauses?q=${encodeURIComponent(q)}&top_k=8`)
    : null;

  return (
    <AppShell session={session} title="Policy manual" crumbs={[{ label: "Policy manual" }]}>
      <Panel title="Search the AutoSure policy manual" subtitle="The same search the agents use. Only clauses that passed the load-time guardrail can appear.">
        <form method="get" className="flex gap-2">
          <input
            id="q"
            name="q"
            type="search"
            defaultValue={q}
            placeholder="e.g. pothole, total loss, policy period"
            className="h-9 flex-1 rounded-lg border border-claimsense-line px-3 text-sm focus:border-claimsense-primary focus:outline-none focus:ring-1 focus:ring-claimsense-primary"
          />
          <button type="submit" className="rounded-lg bg-claimsense-primary px-4 text-sm font-semibold text-white hover:bg-claimsense-deep">
            Search
          </button>
        </form>
      </Panel>

      <div className="mt-4 space-y-3">
        {result === null ? (
          <Empty>Enter at least 3 characters to search.</Empty>
        ) : !result.ok ? (
          <ApiErrorPanel status={result.status} message={result.error.message} />
        ) : result.data.count === 0 ? (
          <Empty>No clause matches “{q}”.</Empty>
        ) : (
          result.data.clauses.map((c) => (
            <Panel key={c.clause_id} title={<span><span className="font-mono">{c.clause_id}</span> · {c.title}</span>}
                   action={<span className="text-xs tabular-nums text-slate-400">score {Number(c.score).toFixed(3)}</span>}>
              <p className="text-sm leading-relaxed text-claimsense-ink">{c.text}</p>
            </Panel>
          ))
        )}
      </div>
    </AppShell>
  );
}
