import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { Empty, ErrorNote, Loading, Page, StatusPill } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { api, errorMessage } from "../services/api";
import type { CrmSync, Lead, Task } from "../types";

const LEAD_STATUS = ["new", "contacted", "quoted", "won", "lost"];

export default function Crm() {
  const lf = useCallback(() => api.get<Lead[]>("/leads"), []);
  const leads = useAsync(lf);
  const tf = useCallback(() => api.get<Task[]>("/tasks?status=open"), []);
  const tasks = useAsync(tf);
  const sf = useCallback(() => api.get<CrmSync[]>("/crm/syncs"), []);
  const syncs = useAsync(sf);
  const cf = useCallback(() => api.get<{ provider: string; healthy: boolean }>("/crm/status"), []);
  const status = useAsync(cf);
  const [err, setErr] = useState<string | null>(null);

  const setLead = async (id: string, s: string) => { try { await api.patch(`/leads/${id}`, { status: s }); await leads.reload(); } catch (e) { setErr(errorMessage(e)); } };
  const done = async (id: string) => { try { await api.patch(`/tasks/${id}`, { status: "done" }); await tasks.reload(); } catch (e) { setErr(errorMessage(e)); } };
  const retry = async (id: string) => { try { await api.post(`/crm/syncs/${id}/retry`); await syncs.reload(); } catch (e) { setErr(errorMessage(e)); } };

  return (
    <Page title="Leads and CRM" sub={status.data ? <span>Provider: <strong>{status.data.provider}</strong> {status.data.healthy ? <span className="pill ok">reachable</span> : <span className="pill bad">unreachable</span>}</span> : undefined}>
      {err && <ErrorNote message={err} />}
      <div className="split">
        <section className="panel"><h3>Leads</h3>
          {leads.loading ? <Loading /> : leads.error ? <ErrorNote message={leads.error} onRetry={leads.reload} /> : leads.data?.length ? (
            <table className="ledger"><thead><tr><th>Name</th><th>Contact</th><th>Status</th></tr></thead><tbody>
              {leads.data.map((l) => (<tr key={l.id}><td>{l.name}{l.is_sample && <> <span className="pill neutral">sample</span></>}{Object.keys(l.preferences).length > 0 && <div className="faint">has saved preferences</div>}</td>
                <td>{l.email}<div className="faint">{l.phone}</div></td>
                <td><label className="sr-only" htmlFor={`s-${l.id}`}>Status for {l.name}</label><select id={`s-${l.id}`} value={l.status} onChange={(e) => setLead(l.id, e.target.value)}>{LEAD_STATUS.map((s) => <option key={s}>{s}</option>)}</select></td></tr>))}
            </tbody></table>) : <Empty title="No leads yet">Leads appear when you create a project.</Empty>}
        </section>
        <div>
          <section className="panel"><h3>Follow-ups</h3>
            {tasks.loading ? <Loading /> : tasks.data?.length ? (<ul style={{ margin: 0, paddingLeft: 0, listStyle: "none" }}>{tasks.data.map((t) => (
              <li key={t.id} className="spread" style={{ borderBottom: "1px solid var(--rule-2)", padding: "8px 0" }}><span>{t.title}{t.project_id && <> · <Link to={`/projects/${t.project_id}/crm`}>project</Link></>}</span><button className="quiet" onClick={() => done(t.id)}>Mark done</button></li>))}</ul>
            ) : <p className="muted">Nothing to follow up.</p>}
          </section>
          <section className="panel"><h3>Sync log</h3>
            {syncs.loading ? <Loading /> : syncs.data?.length ? (<table className="ledger"><tbody>{syncs.data.slice(0, 10).map((s) => (
              <tr key={s.id}><td><StatusPill status={s.status} /> <span className="faint">{s.provider}</span>{s.last_error && <div className="faint">{s.last_error}</div>}</td><td className="r">{s.status !== "synced" && <button className="quiet" onClick={() => retry(s.id)}>Retry</button>}</td></tr>))}</tbody></table>
            ) : <p className="muted">No syncs yet. Approved quotes are written here.</p>}
          </section>
        </div>
      </div>
    </Page>
  );
}
