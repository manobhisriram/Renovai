import { useState } from "react";
import type { Option, Quote, Tier } from "../types";
import { Confidence, Money, StatusPill } from "./ui";

const TIER_LABEL: Record<string, string> = { budget: "Budget", standard: "Standard", premium: "Premium", fitted: "Fitted to your budget" };

export function QuoteView({ quote, tier, onTier }: { quote: Quote; tier: Tier; onTier?: (t: Tier) => void }) {
  const p = quote.payload;
  const tiers = (["budget", "standard", "premium", "fitted"] as Tier[]).filter((t) => p.options[t]);
  const opt = p.options[tier] as Option | undefined;
  const [showLines, setShowLines] = useState(true);
  if (!opt) return null;
  const cur = quote.currency;
  return (
    <div className="stack">
      <div className="spread">
        <div className="row"><h2>Quote v{quote.version}</h2><StatusPill status={quote.status} /><Confidence value={quote.confidence} />
          {quote.parent_version && <span className="faint">revises v{quote.parent_version}</span>}</div>
      </div>
      <p className="muted">{p.narrative.summary}</p>

      <div className="tier-pick" role="group" aria-label="Quote option">
        {tiers.map((t) => {
          const o = p.options[t] as Option;
          return (
            <button key={t} aria-pressed={t === tier} onClick={() => onTier?.(t)} disabled={!onTier}>
              <span className="t">{TIER_LABEL[t]}</span><span className="num" style={{ fontSize: 20, fontWeight: 700 }}><Money value={o.total} currency={cur} /></span>
              <span className="t">{o.timeline.weeks} weeks</span>
            </button>
          );
        })}
      </div>

      <div className="panel">
        <div className="spread"><h3>{TIER_LABEL[tier]} breakdown</h3><button className="quiet" onClick={() => setShowLines(!showLines)}>{showLines ? "Hide lines" : "Show lines"}</button></div>
        {showLines && (
          <div style={{ overflowX: "auto" }}><table className="ledger"><thead><tr><th>Item</th><th>Qty</th><th className="r">Materials</th><th className="r">Labour</th><th className="r">Line total</th></tr></thead><tbody>
            {opt.lines.map((l) => (
              <tr key={l.group}><td>{l.name}<div className="faint">{l.tier} · {l.group.replace(/_/g, " ")}{l.optional && " · optional"}</div></td>
                <td className="num">{l.quantity.toLocaleString("en-IN")} {l.unit}</td><td className="r"><Money value={l.material_cost} currency={cur} /></td>
                <td className="r"><Money value={l.labor_cost} currency={cur} /><div className="faint">{l.labor_hours} h</div></td><td className="r"><Money value={l.line_total} currency={cur} /></td></tr>))}
          </tbody></table></div>)}
        <table className="ledger" style={{ marginTop: 10 }}><tbody>
          <tr><td>Materials</td><td className="r"><Money value={opt.materials_subtotal} currency={cur} /></td></tr>
          <tr><td>Labour</td><td className="r"><Money value={opt.labor_subtotal} currency={cur} /></td></tr>
          <tr><td>Logistics ({opt.params.logistics_pct}%)</td><td className="r"><Money value={opt.logistics} currency={cur} /></td></tr>
          <tr><td>Contingency ({opt.params.contingency_pct}%)</td><td className="r"><Money value={opt.contingency} currency={cur} /></td></tr>
          <tr><td>Tax ({opt.params.tax_pct}%)</td><td className="r"><Money value={opt.tax} currency={cur} /></td></tr>
          <tr className="total"><td>Estimated total</td><td className="r"><Money value={opt.total} currency={cur} /></td></tr>
        </tbody></table>
        <p className="faint">Region {opt.params.region} (×{opt.params.region_multiplier}), complexity {opt.params.complexity}. Every figure is computed by the pricing engine, not by the AI.</p>
        {opt.timeline.critical_material && <p className="faint">Longest lead time: {opt.timeline.critical_material}.</p>}
      </div>

      {p.negotiation && p.negotiation.steps.length > 0 && (
        <div className="panel"><h3>What changed to fit the budget</h3>
          <ul>{p.tradeoffs.map((t, i) => <li key={i}>{t}</li>)}</ul>
        </div>)}

      <div className="cols">
        <div className="panel"><h3>Assumptions</h3><ul>{p.assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul></div>
        <div className="panel"><h3>Exclusions</h3>{p.exclusions.length ? <ul>{p.exclusions.map((a, i) => <li key={i}>{a}</li>)}</ul> : <p className="muted">None listed.</p>}</div>
        <div className="panel"><h3>Risks</h3>{p.risks.length ? <ul>{p.risks.map((a, i) => <li key={i}>{a}</li>)}</ul> : <p className="muted">None listed.</p>}</div>
      </div>

      <div className="panel"><h3>Checks</h3>
        {p.validation.flags.length === 0 ? <p className="muted">All automatic checks passed.</p> : (
          <ul style={{ margin: 0, paddingLeft: 18 }}>{p.validation.flags.map((f, i) => <li key={i}><span className={`pill ${f.blocking ? "bad" : f.severity === "info" ? "info" : "warn"}`}>{f.blocking ? "needs review" : f.severity}</span> {f.message}</li>)}</ul>)}
      </div>
      <p className="faint">{p.disclaimer}</p>
    </div>
  );
}
