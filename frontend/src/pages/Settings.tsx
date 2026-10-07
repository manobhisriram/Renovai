import { useCallback } from "react";
import { ErrorNote, Loading, Money, Page } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { api } from "../services/api";
import type { SystemConfig } from "../types";

export default function Settings() {
  const fn = useCallback(() => api.get<SystemConfig>("/system/config"), []);
  const c = useAsync(fn);
  if (c.loading) return <Loading />;
  if (c.error || !c.data) return <ErrorNote message={c.error ?? "No data"} onRetry={c.reload} />;
  const d = c.data;
  return (
    <Page title="Settings" sub={`Environment ${d.env} · version ${d.version}. Change these through server environment variables.`}>
      {d.configuration_problems.length > 0 && <div className="callout bad" role="alert"><strong>Configuration needs attention.</strong><ul>{d.configuration_problems.map((p, i) => <li key={i}>{p}</li>)}</ul></div>}
      <div className="cols">
        <section className="panel"><h3>Model routing</h3><p className="muted">Provider: <strong>{d.llm.provider}</strong>{d.llm.fallback_enabled && " · falls back to a cheaper tier if a model is unavailable"}</p>
          <table className="ledger"><thead><tr><th>Tier</th><th>Model</th></tr></thead><tbody>{Object.entries(d.llm.models).map(([t, m]) => <tr key={t}><td>{t}</td><td className="num">{m}</td></tr>)}</tbody></table>
          <h4 style={{ marginTop: 14 }}>Task to tier</h4><table className="ledger"><tbody>{Object.entries(d.llm.task_tiers).map(([t, v]) => <tr key={t}><td>{t.replace(/_/g, " ")}</td><td>{v}</td></tr>)}</tbody></table></section>
        <section className="panel"><h3>Services</h3><table className="ledger"><tbody>
          <tr><td>Vector database</td><td>Qdrant, {d.rag.remote ? "remote" : "embedded"} · {d.rag.collection}</td></tr><tr><td>Embeddings</td><td>{d.rag.embedder}</td></tr><tr><td>CRM</td><td>{d.crm.provider}</td></tr>
          <tr><td>Image storage</td><td>{d.storage}</td></tr><tr><td>Renders</td><td>{d.visualization === "none" ? "off" : d.visualization}</td></tr><tr><td>Workflow state</td><td>{d.checkpointing}</td></tr><tr><td>Redis</td><td>{d.redis ? "connected" : "not used"}</td></tr>
          <tr><td>Metrics</td><td>{d.observability.metrics ? "Prometheus" : "off"}{d.observability.langfuse && " · Langfuse"}{d.observability.otel && " · OpenTelemetry"}</td></tr></tbody></table></section>
        <section className="panel"><h3>Approval policy</h3><table className="ledger"><tbody>
          <tr><td>Every quote needs approval</td><td>{d.approval.always ? "yes" : "no"}</td></tr><tr><td>Also required above</td><td><Money value={d.approval.total_threshold} /></td></tr><tr><td>Also required below confidence</td><td className="num">{d.approval.min_confidence}</td></tr></tbody></table>
          <h4 style={{ marginTop: 14 }}>Pricing defaults</h4><table className="ledger"><tbody>{Object.entries(d.pricing_defaults).map(([k, v]) => <tr key={k}><td>{k.replace(/_/g, " ")}</td><td className="num">{String(v)}</td></tr>)}</tbody></table></section>
      </div>
    </Page>
  );
}
