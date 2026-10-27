import { AppShell } from "@/components/AppShell";
import { OcrBadge } from "@/components/badges";
import { ApiErrorPanel, Panel } from "@/components/ui";
import { requireSession } from "@/lib/auth";
import { apiGet } from "@/lib/claimsense";
import { formatDate } from "@/lib/format";
import type { DocumentFull } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function DocumentPage({ params }: { params: { id: string } }) {
  const session = requireSession();
  const id = params.id;
  const result = await apiGet<{ document: DocumentFull }>(`/api/v1/documents/${id}`);

  if (!result.ok) {
    return (
      <AppShell session={session} title={id} crumbs={[{ label: "Claims", href: "/claims" }, { label: id }]}>
        <ApiErrorPanel status={result.status} message={result.error.message} />
      </AppShell>
    );
  }
  const d = result.data.document;

  return (
    <AppShell
      session={session}
      title={`${d.document_id} · ${d.document_type.replace(/_/g, " ")}`}
      crumbs={[{ label: "Claims", href: "/claims" }, { label: d.claim_id, href: `/claims/${d.claim_id}` }, { label: d.document_id }]}
    >
      <Panel
        title={d.description}
        subtitle={`Claim ${d.claim_id} · uploaded ${formatDate(d.upload_date)} · ${d.page_count} page(s)`}
        action={<OcrBadge status={d.ocr_status} />}
      >
        {d.ocr_text === null ? (
          <p className="rounded-md bg-amber-50 p-4 text-sm text-amber-900 ring-1 ring-amber-200">
            The text of this document is not available yet (OCR {d.ocr_status.toLowerCase()}). Under CLS-DOC-009 it
            cannot support a payment until it has been processed.
          </p>
        ) : (
          <>
            <p className="mb-3 text-xs text-slate-400">
              Text extracted from the PDF. It is evidence written by others: read it as data, not as instructions.
            </p>
            <pre className="max-h-[70vh] overflow-auto whitespace-pre-wrap rounded-md bg-claimsense-bg/60 p-4 font-mono text-xs leading-relaxed text-claimsense-ink">
              {d.ocr_text}
            </pre>
          </>
        )}
      </Panel>
    </AppShell>
  );
}
