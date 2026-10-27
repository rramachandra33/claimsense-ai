import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { ClaimStatusBadge } from "@/components/badges";
import { ApiErrorPanel, Empty, Panel } from "@/components/ui";
import { requireSession } from "@/lib/auth";
import { apiGet } from "@/lib/claimsense";
import { formatDate, formatUsd } from "@/lib/format";
import type { Claim } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function ClaimsPage() {
  const session = requireSession();
  const result = await apiGet<{ claims: Claim[]; count: number }>("/api/v1/claims");

  return (
    <AppShell session={session} title="Claims" crumbs={[{ label: "Claims" }]}>
      {!result.ok ? (
        <ApiErrorPanel status={result.status} message={result.error.message} />
      ) : (
        <Panel
          title="Your claims"
          subtitle={`${result.data.count} claim(s) you are allowed to work on. The list comes from the ClaimSense API, which applies your access rules.`}
          bodyClassName="p-0"
        >
          {result.data.count === 0 ? (
            <Empty>No claims are assigned to you or in your queue.</Empty>
          ) : (
            <table className="w-full text-sm">
              <thead className="border-b border-claimsense-line bg-claimsense-bg/60 text-left text-[11px] uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-2">Claim</th>
                  <th className="px-4 py-2">Incident</th>
                  <th className="px-4 py-2">Vehicle</th>
                  <th className="px-4 py-2 text-right">Estimate</th>
                  <th className="px-4 py-2 text-right">ACV</th>
                  <th className="px-4 py-2 text-right">Fraud score</th>
                  <th className="px-4 py-2">Status</th>
                  <th className="px-4 py-2">Adjuster</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-claimsense-line">
                {result.data.claims.map((c) => (
                  <tr key={c.claim_id} className="hover:bg-claimsense-bg/50">
                    <td className="px-4 py-2.5">
                      <Link href={`/claims/${c.claim_id}`} className="font-mono font-medium text-claimsense-primary hover:underline">
                        {c.claim_id}
                      </Link>
                    </td>
                    <td className="px-4 py-2.5">
                      <div>{c.incident_type}</div>
                      <div className="text-xs text-slate-400">{formatDate(c.incident_date)}</div>
                    </td>
                    <td className="px-4 py-2.5">{c.vehicle_year} {c.vehicle_make} {c.vehicle_model}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums">{formatUsd(c.repair_estimate_usd)}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums">{formatUsd(c.vehicle_acv_usd)}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums">{Number(c.fraud_risk_score).toFixed(2)}</td>
                    <td className="px-4 py-2.5"><ClaimStatusBadge status={c.claim_status} /></td>
                    <td className="px-4 py-2.5 font-mono text-xs">{c.assigned_adjuster}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
      )}
    </AppShell>
  );
}
