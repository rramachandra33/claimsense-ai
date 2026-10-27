import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { ClaimStatusBadge, OcrBadge } from "@/components/badges";
import { ApiErrorPanel, Field, Panel } from "@/components/ui";
import { requireSession } from "@/lib/auth";
import { apiGet } from "@/lib/claimsense";
import { formatDate, formatUsd } from "@/lib/format";
import type { Claim, DocumentRow, Note, Policy } from "@/lib/types";
import { NotesList } from "./NotesList";
import { RunAssessment } from "./RunAssessment";

export const dynamic = "force-dynamic";

function yesNo(value: boolean) {
  return value ? "Yes" : "No";
}

export default async function ClaimPage({ params }: { params: { id: string } }) {
  const session = requireSession();
  const id = params.id;
  const crumbs = [{ label: "Claims", href: "/claims" }, { label: id }];

  const claimResult = await apiGet<{ claim: Claim }>(`/api/v1/claims/${id}`);
  if (!claimResult.ok) {
    return (
      <AppShell session={session} title={id} crumbs={crumbs}>
        <ApiErrorPanel status={claimResult.status} message={claimResult.error.message} />
      </AppShell>
    );
  }
  const claim = claimResult.data.claim;
  const policyResult = await apiGet<{ policy: Policy }>(`/api/v1/claims/${id}/policy`);
  const docsResult = await apiGet<{ documents: DocumentRow[] }>(`/api/v1/claims/${id}/documents`);
  const notesResult = await apiGet<{ notes: Note[] }>(`/api/v1/claims/${id}/notes`);

  return (
    <AppShell session={session} title={`${claim.claim_id} · ${claim.incident_type}`} crumbs={crumbs}>
      <div className="grid gap-4 lg:grid-cols-3">
        <Panel title="ClaimSense assessment" subtitle="Draft decisions for you to confirm. Nothing is paid or closed automatically." className="lg:col-span-3">
          <RunAssessment claimId={claim.claim_id} />
          <div className="mt-4 border-t border-claimsense-line pt-4">
            {!notesResult.ok ? (
              <ApiErrorPanel status={notesResult.status} message={notesResult.error.message} />
            ) : (
              <NotesList notes={notesResult.data.notes} />
            )}
          </div>
        </Panel>

        <Panel title="Claim" subtitle="From claims management" className="lg:col-span-2" action={<ClaimStatusBadge status={claim.claim_status} />}>
          <dl className="grid grid-cols-2 gap-4 md:grid-cols-3">
            <Field label="Incident date">{formatDate(claim.incident_date)}</Field>
            <Field label="Incident type">{claim.incident_type}</Field>
            <Field label="Assigned adjuster"><span className="font-mono">{claim.assigned_adjuster}</span></Field>
            <Field label="Vehicle">{claim.vehicle_year} {claim.vehicle_make} {claim.vehicle_model}</Field>
            <Field label="VIN"><span className="font-mono text-xs">{claim.vehicle_vin}</span></Field>
            <Field label="ACV at loss">{formatUsd(claim.vehicle_acv_usd)}</Field>
            <Field label="Repair estimate">{formatUsd(claim.repair_estimate_usd)}</Field>
            <Field label="Injuries reported">{yesNo(claim.injuries_reported)}</Field>
            <Field label="Police report filed">{yesNo(claim.police_report_filed)}</Field>
            <Field label="Prior claims (12 months)">{claim.prior_claims_12mo}</Field>
            <Field label="Vendor fraud score">{Number(claim.fraud_risk_score).toFixed(2)}</Field>
          </dl>
          <div className="mt-5 space-y-3 border-t border-claimsense-line pt-4 text-sm">
            <div>
              <div className="text-[11px] font-medium uppercase tracking-wide text-slate-400">What happened (claimant)</div>
              <p className="mt-0.5 text-claimsense-ink">{claim.incident_description}</p>
            </div>
            <div>
              <div className="text-[11px] font-medium uppercase tracking-wide text-slate-400">Damage</div>
              <p className="mt-0.5 text-claimsense-ink">{claim.damage_description}</p>
            </div>
          </div>
        </Panel>

        <Panel title="Policy" subtitle="From policy administration">
          {!policyResult.ok ? (
            <ApiErrorPanel status={policyResult.status} message={policyResult.error.message} />
          ) : (
            <dl className="grid grid-cols-2 gap-4">
              <Field label="Policy">{policyResult.data.policy.policy_id}</Field>
              <Field label="Cover">{policyResult.data.policy.coverage_type}</Field>
              <Field label="Period start">{formatDate(policyResult.data.policy.policy_start)}</Field>
              <Field label="Period end">{formatDate(policyResult.data.policy.policy_end)}</Field>
              <Field label="Collision deductible">{formatUsd(policyResult.data.policy.collision_deductible_usd)}</Field>
              <Field label="Comprehensive deductible">{formatUsd(policyResult.data.policy.comprehensive_deductible_usd)}</Field>
              <Field label="Status field">
                {policyResult.data.policy.policy_status}
                <span className="block text-[11px] text-slate-400">administrative; dates decide cover</span>
              </Field>
            </dl>
          )}
        </Panel>

        <Panel title="Documents" subtitle="From the document store" className="lg:col-span-3" bodyClassName="p-0">
          {!docsResult.ok ? (
            <div className="p-4"><ApiErrorPanel status={docsResult.status} message={docsResult.error.message} /></div>
          ) : (
            <table className="w-full text-sm">
              <thead className="border-b border-claimsense-line bg-claimsense-bg/60 text-left text-[11px] uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-2">Document</th>
                  <th className="px-4 py-2">Type</th>
                  <th className="px-4 py-2">Description</th>
                  <th className="px-4 py-2">Uploaded</th>
                  <th className="px-4 py-2 text-right">Pages</th>
                  <th className="px-4 py-2">Text</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-claimsense-line">
                {docsResult.data.documents.map((d) => (
                  <tr key={d.document_id} className="hover:bg-claimsense-bg/50">
                    <td className="px-4 py-2.5">
                      <Link href={`/documents/${d.document_id}`} className="font-mono font-medium text-claimsense-primary hover:underline">
                        {d.document_id}
                      </Link>
                    </td>
                    <td className="px-4 py-2.5 text-xs">{d.document_type.replace(/_/g, " ")}</td>
                    <td className="px-4 py-2.5">{d.description}</td>
                    <td className="px-4 py-2.5">{formatDate(d.upload_date)}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums">{d.page_count}</td>
                    <td className="px-4 py-2.5"><OcrBadge status={d.ocr_status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
      </div>
    </AppShell>
  );
}
