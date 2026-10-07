import { useCallback, useState } from "react";
import { Empty, ErrorNote, Loading, Money, StatusPill } from "../../components/ui";
import { QuoteView } from "../../components/QuoteView";
import { useAsync } from "../../hooks/useAsync";
import { api } from "../../services/api";
import type { Quote, QuoteSummary } from "../../types";

export function HistoryTab({ projectId, version }: { projectId: string; version: number }) {
  const fn = useCallback(() => api.get<QuoteSummary[]>(`/projects/${projectId}/quotes`), [projectId, version]); // eslint-disable-line react-hooks/exhaustive-deps
  const list = useAsync(fn);
  const [open, setOpen] = useState<number | null>(null);
  const qFn = useCallback(() => (open ? api.get<Quote>(`/projects/${projectId}/quotes/${open}`) : Promise.resolve(null)), [projectId, open]);
  const detail = useAsync(qFn);
  if (list.loading) return <Loading />;
  if (list.error) return <ErrorNote message={list.error} onRetry={list.reload} />;
  if (!list.data?.length) return <Empty title="No versions yet">Each revision creates a new version; earlier ones are never changed.</Empty>;
  return (
    <div className="stack">
      <section className="panel"><h3>Quote versions</h3>
        <table className="ledger"><thead><tr><th>Version</th><th>Reason</th><th>Status</th><th>Option</th><th className="r">Total</th><th /></tr></thead><tbody>
          {list.data.map((q) => (<tr key={q.id}><td>v{q.version}{q.parent_version && <span className="faint"> from v{q.parent_version}</span>}</td><td>{q.reason}</td><td><StatusPill status={q.status} /></td><td>{q.selected_tier}</td>
            <td className="r"><Money value={q.total} currency={q.currency} /></td><td className="r"><button className="quiet" onClick={() => setOpen(open === q.version ? null : q.version)}>{open === q.version ? "Close" : "View"}</button></td></tr>))}
        </tbody></table></section>
      {open && (detail.loading ? <Loading /> : detail.data && <QuoteView quote={detail.data} tier={detail.data.selected_tier} />)}
    </div>
  );
}
