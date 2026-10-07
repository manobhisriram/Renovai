import { useCallback, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Empty, ErrorNote, Loading, Money, Page, StatusPill } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { api } from "../services/api";
import type { Project } from "../types";

const STATUSES = ["", "draft", "analyzing", "awaiting_clarification", "awaiting_approval", "approved", "rejected", "failed"];

export default function Projects() {
  const nav = useNavigate();
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const fn = useCallback(() => api.get<Project[]>(`/projects?${new URLSearchParams({ ...(status && { status }), ...(q && { q }) })}`), [status, q]);
  const list = useAsync(fn);
  return (
    <Page title="Projects" actions={<Link className="btn primary" to="/projects/new">New project</Link>}>
      <div className="row" style={{ marginBottom: 16 }}>
        <div style={{ width: 260 }}><label htmlFor="q" className="sr-only">Search by title</label><input id="q" placeholder="Search by title" value={q} onChange={(e) => setQ(e.target.value)} /></div>
        <div style={{ width: 220 }}><label htmlFor="st" className="sr-only">Status</label>
          <select id="st" value={status} onChange={(e) => setStatus(e.target.value)}>{STATUSES.map((s) => <option key={s} value={s}>{s ? s.replace(/_/g, " ") : "All statuses"}</option>)}</select></div>
      </div>
      {list.loading ? <Loading /> : list.error ? <ErrorNote message={list.error} onRetry={list.reload} /> : list.data?.length ? (
        <div className="panel"><table className="ledger"><thead><tr><th>Project</th><th>Client</th><th>Category</th><th>Status</th><th className="r">Quote</th></tr></thead><tbody>
          {list.data.map((p) => (
            <tr key={p.id} className="click" onClick={() => nav(`/projects/${p.id}`)}>
              <td><Link to={`/projects/${p.id}`}>{p.title}</Link><div className="faint">{p.image_count} photo{p.image_count === 1 ? "" : "s"}</div></td>
              <td>{p.lead.name}</td><td>{p.category?.replace(/_/g, " ") ?? <span className="faint">not classified</span>}</td>
              <td><StatusPill status={p.status} /></td><td className="r"><Money value={p.summary.total} currency={p.summary.currency} /></td>
            </tr>))}
        </tbody></table></div>
      ) : <Empty title="No matching projects" action={<Link className="btn primary" to="/projects/new">New project</Link>}>Adjust the filters or create a project.</Empty>}
    </Page>
  );
}
