import { useCallback } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Empty, ErrorNote, Loading, Money, Page, StatusPill } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { api } from "../services/api";
import type { Analytics, Approval, Project, Task } from "../types";

export default function Dashboard() {
  const nav = useNavigate();
  const projFn = useCallback(() => api.get<Project[]>("/projects?limit=8"), []);
  const projects = useAsync(projFn);
  const aFn = useCallback(() => api.get<Analytics>("/analytics/summary"), []);
  const stats = useAsync(aFn);
  const apFn = useCallback(() => api.get<Approval[]>("/approvals?status=pending"), []);
  const approvals = useAsync(apFn);
  const tFn = useCallback(() => api.get<Task[]>("/tasks?status=open"), []);
  const tasks = useAsync(tFn);

  const s = stats.data;
  return (
    <Page title="Today at the desk" sub="Quotes waiting on a person come first." actions={<Link className="btn primary" to="/projects/new">New project</Link>}>
      <div className="split">
        <div>
          <section className="panel" aria-labelledby="wait-h">
            <h3 id="wait-h">Waiting for approval</h3>
            {approvals.loading ? <Loading /> : approvals.error ? <ErrorNote message={approvals.error} onRetry={approvals.reload} /> :
              approvals.data?.length ? (
                <table className="ledger"><thead><tr><th>Project</th><th>Version</th><th className="r">Total</th></tr></thead><tbody>
                  {approvals.data.map((a) => (
                    <tr key={a.id} className="click" onClick={() => nav(`/projects/${a.project_id}/quote`)}>
                      <td><Link to={`/projects/${a.project_id}/quote`}>{a.project_title}</Link><div className="faint">{a.reasons[0]}</div></td>
                      <td>v{a.quote_version}</td><td className="r"><Money value={a.quote_total} currency={a.currency} /></td>
                    </tr>))}
                </tbody></table>
              ) : <Empty title="Nothing waiting">Every quote has been reviewed.</Empty>}
          </section>
          <section className="panel" aria-labelledby="proj-h">
            <h3 id="proj-h">Recent projects</h3>
            {projects.loading ? <Loading /> : projects.error ? <ErrorNote message={projects.error} onRetry={projects.reload} /> :
              projects.data?.length ? (
                <table className="ledger"><thead><tr><th>Project</th><th>Client</th><th>Status</th><th className="r">Quote</th></tr></thead><tbody>
                  {projects.data.map((p) => (
                    <tr key={p.id} className="click" onClick={() => nav(`/projects/${p.id}`)}>
                      <td><Link to={`/projects/${p.id}`}>{p.title}</Link></td><td>{p.lead.name}</td><td><StatusPill status={p.status} /></td>
                      <td className="r"><Money value={p.summary.total} currency={p.summary.currency} /></td>
                    </tr>))}
                </tbody></table>
              ) : <Empty title="No projects yet" action={<Link className="btn primary" to="/projects/new">Create the first project</Link>}>Start with a client's photos and a short description.</Empty>}
          </section>
        </div>
        <div>
          <section className="panel" aria-labelledby="num-h">
            <h3 id="num-h">Approved so far</h3>
            {stats.loading ? <Loading /> : s ? (
              <>
                <div className="big-total"><Money value={s.approved_value} compact /></div>
                <p className="muted">{s.approved_quotes} approved quote{s.approved_quotes === 1 ? "" : "s"}. Average confidence {s.avg_quote_confidence.toFixed(2)}.</p>
                {s.avg_workflow_seconds !== null && <p className="muted">Analysis takes {s.avg_workflow_seconds}s on average.</p>}
              </>) : <ErrorNote message={stats.error ?? "No data"} onRetry={stats.reload} />}
          </section>
          <section className="panel" aria-labelledby="task-h">
            <h3 id="task-h">Follow-ups</h3>
            {tasks.loading ? <Loading /> : tasks.data?.length ? (
              <ul style={{ margin: 0, paddingLeft: 18 }}>{tasks.data.slice(0, 6).map((t) => <li key={t.id}>{t.title}</li>)}</ul>
            ) : <p className="muted">No open follow-ups.</p>}
            <p><Link to="/crm">Open leads and CRM</Link></p>
          </section>
        </div>
      </div>
    </Page>
  );
}
