import { useCallback } from "react";
import { ErrorNote, Loading, Money, Page } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { api } from "../services/api";
import type { Analytics as A } from "../types";

function Counts({ title, data }: { title: string; data: Record<string, number> }) {
  const rows = Object.entries(data);
  return <section className="panel"><h3>{title}</h3>{rows.length ? <table className="ledger"><tbody>{rows.map(([k, v]) => <tr key={k}><td>{k.replace(/_/g, " ")}</td><td className="r num">{v}</td></tr>)}</tbody></table> : <p className="muted">No data yet.</p>}</section>;
}

export default function Analytics() {
  const fn = useCallback(() => api.get<A>("/analytics/summary?days=30"), []);
  const a = useAsync(fn);
  if (a.loading) return <Loading />;
  if (a.error || !a.data) return <ErrorNote message={a.error ?? "No data"} onRetry={a.reload} />;
  const d = a.data;
  const totalCalls = d.llm.reduce((s, r) => s + r.calls, 0);
  return (
    <Page title="Analytics" sub="Last 30 days.">
      <div className="cols">
        <section className="panel"><h3>Approved value</h3><div className="big-total"><Money value={d.approved_value} compact /></div><p className="muted">{d.approved_quotes} quotes</p></section>
        <section className="panel"><h3>Quote confidence</h3><div className="big-total">{d.avg_quote_confidence.toFixed(2)}</div><p className="muted">average across all quotes</p></section>
        <section className="panel"><h3>Client feedback</h3><div className="big-total">{d.feedback.net >= 0 ? "+" : ""}{d.feedback.net}</div><p className="muted">net of {d.feedback.count} ratings</p></section>
      </div>
      <div className="cols" style={{ marginTop: 16 }}>
        <Counts title="Projects" data={d.projects_by_status} /><Counts title="Quotes" data={d.quotes_by_status} /><Counts title="Approvals" data={d.approvals_by_status} /><Counts title="CRM syncs" data={d.crm_syncs_by_status} />
      </div>
      <section className="panel" style={{ marginTop: 16 }}><h3>AI usage and model routing</h3>
        {d.mock_ai && <div className="callout">Mock AI is active, so these rows describe the test double, not a real model.</div>}
        {d.llm.length === 0 ? <p className="muted">No model calls recorded yet.</p> : (
          <table className="ledger"><thead><tr><th>Model</th><th>Tier</th><th className="r">Calls</th><th className="r">Avg latency</th><th className="r">Tokens in/out</th><th className="r">Est. cost</th><th className="r">Errors</th></tr></thead><tbody>
            {d.llm.map((r) => (<tr key={r.model + r.tier}><td>{r.model}</td><td>{r.tier}</td><td className="r num">{r.calls}</td><td className="r num">{r.avg_latency_ms} ms</td><td className="r num">{r.input_tokens.toLocaleString()} / {r.output_tokens.toLocaleString()}</td>
              <td className="r num">{r.est_cost_usd === null ? <span className="faint" title="Set LLM_PRICING_JSON to see estimates">n/a</span> : `$${r.est_cost_usd.toFixed(4)}`}</td><td className="r num">{r.errors}</td></tr>))}
            <tr className="total"><td colSpan={2}>Total</td><td className="r num">{totalCalls}</td><td colSpan={4} /></tr>
          </tbody></table>)}
      </section>
    </Page>
  );
}
