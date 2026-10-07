import { useCallback, useState } from "react";
import { Empty, ErrorNote, Loading, StatusPill } from "../../components/ui";
import { useAsync } from "../../hooks/useAsync";
import { api, errorMessage } from "../../services/api";
import type { CrmSync, Project } from "../../types";

export function CrmTab({ project, version }: { project: Project; version: number }) {
  const fn = useCallback(() => api.get<CrmSync[]>("/crm/syncs"), [version]); // eslint-disable-line react-hooks/exhaustive-deps
  const syncs = useAsync(fn);
  const [err, setErr] = useState<string | null>(null);
  const mine = syncs.data?.filter((s) => s.project_id === project.id) ?? [];
  const retry = async (id: string) => { setErr(null); try { await api.post(`/crm/syncs/${id}/retry`); await syncs.reload(); } catch (e) { setErr(errorMessage(e)); } };
  return (
    <div className="stack">
      <section className="panel"><h3>Client record</h3>
        <table className="ledger"><tbody>
          <tr><td style={{ width: 120 }}>Name</td><td>{project.lead.name}</td></tr><tr><td>Email</td><td>{project.lead.email ?? <span className="faint">not provided</span>}</td></tr>
          <tr><td>Phone</td><td>{project.lead.phone ?? <span className="faint">not provided</span>}</td></tr><tr><td>Lead status</td><td><StatusPill status={project.lead.status} /></td></tr>
          {Object.keys(project.lead.preferences).length > 0 && <tr><td>Preferences</td><td>{JSON.stringify(project.lead.preferences)}</td></tr>}
        </tbody></table></section>
      <section className="panel"><h3>CRM sync</h3>
        <p className="muted">A lead is written to the CRM only after a quote is approved, and each quote version is written at most once.</p>
        {syncs.loading ? <Loading /> : syncs.error ? <ErrorNote message={syncs.error} onRetry={syncs.reload} /> : mine.length === 0 ? <Empty title="Not synced yet">Approve a quote to hand this lead to the CRM.</Empty> : (
          <table className="ledger"><thead><tr><th>Reference</th><th>Provider</th><th>Status</th><th>Attempts</th><th /></tr></thead><tbody>
            {mine.map((s) => (<tr key={s.id}><td className="num">{s.idempotency_key.split(":")[1]}</td><td>{s.provider}</td><td><StatusPill status={s.status} />{s.last_error && <div className="faint">{s.last_error}</div>}</td>
              <td>{s.attempts}</td><td className="r">{s.status !== "synced" && <button onClick={() => retry(s.id)}>Retry sync</button>}</td></tr>))}
          </tbody></table>)}
        {err && <ErrorNote message={err} />}
      </section>
    </div>
  );
}
