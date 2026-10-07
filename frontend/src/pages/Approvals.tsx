import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { Confidence, Empty, ErrorNote, Loading, Money, Page, StatusPill } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { api } from "../services/api";
import type { Approval } from "../types";

export default function Approvals() {
  const [status, setStatus] = useState("pending");
  const fn = useCallback(() => api.get<Approval[]>(`/approvals?status=${status}`), [status]);
  const list = useAsync(fn);
  return (
    <Page title="Approvals" sub="Open a quote to approve it, pick the option the client sees, or reject it with a note.">
      <div className="tabs" role="tablist" aria-label="Approval status">
        {["pending", "approved", "rejected"].map((s) => <button key={s} role="tab" aria-selected={status === s} onClick={() => setStatus(s)}>{s[0].toUpperCase() + s.slice(1)}</button>)}
      </div>
      {list.loading ? <Loading /> : list.error ? <ErrorNote message={list.error} onRetry={list.reload} /> : list.data?.length ? (
        <div className="panel"><table className="ledger"><thead><tr><th>Project</th><th>Why it needs a person</th><th>Confidence</th><th className="r">Total</th><th>Status</th></tr></thead><tbody>
          {list.data.map((a) => (<tr key={a.id}><td><Link to={`/projects/${a.project_id}/quote`}>{a.project_title}</Link><div className="faint">v{a.quote_version} · {a.selected_tier}</div></td>
            <td>{a.reasons.map((r, i) => <div key={i}>{r}</div>)}{a.decision_note && <div className="faint">Note: {a.decision_note}</div>}</td><td><Confidence value={a.confidence} /></td>
            <td className="r"><Money value={a.quote_total} currency={a.currency} /></td><td><StatusPill status={a.status} /></td></tr>))}
        </tbody></table></div>) : <Empty title={`No ${status} approvals`}>{status === "pending" ? "You are all caught up." : "Decisions will be listed here."}</Empty>}
    </Page>
  );
}
