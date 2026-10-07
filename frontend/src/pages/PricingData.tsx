import { useCallback, useState } from "react";
import { ErrorNote, Loading, Money, Page } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { api, errorMessage } from "../services/api";
import { useAuth } from "../stores/auth";
import type { Material } from "../types";

interface Cfg { labor_rates: { trade: string; hourly_rate: number; is_sample: boolean }[]; regions: { key: string; name: string; multiplier: number; is_sample: boolean }[]; formula: string }

export default function PricingData() {
  const admin = useAuth((s) => s.user?.role === "admin");
  const mf = useCallback(() => api.get<Material[]>("/materials"), []);
  const mats = useAsync(mf);
  const cf = useCallback(() => api.get<Cfg>("/pricing/config"), []);
  const cfg = useAsync(cf);
  const [edit, setEdit] = useState<{ sku: string; price: string } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const save = async () => {
    if (!edit) return;
    try { await api.put(`/materials/${edit.sku}`, { unit_price: Number(edit.price) }); setEdit(null); await mats.reload(); } catch (e) { setErr(errorMessage(e)); }
  };
  const anySample = mats.data?.some((m) => m.is_sample);
  return (
    <Page title="Pricing data" sub="The numbers behind every quote. The AI chooses materials and quantities; these tables set the prices.">
      {anySample && <div className="callout"><strong>Sample prices.</strong> The seeded catalog uses illustrative rates, not market prices. Edit them before quoting real clients.</div>}
      {cfg.data && <p className="faint">{cfg.data.formula}</p>}
      {err && <ErrorNote message={err} />}
      <div className="split">
        <section className="panel"><h3>Materials</h3>
          {mats.loading ? <Loading /> : mats.error ? <ErrorNote message={mats.error} onRetry={mats.reload} /> : (
            <div style={{ overflowX: "auto" }}><table className="ledger"><thead><tr><th>Item</th><th>Tier</th><th>Unit</th><th className="r">Price</th><th>Lead</th><th /></tr></thead><tbody>
              {mats.data?.map((m) => (<tr key={m.sku}><td>{m.name}<div className="faint">{m.group.replace(/_/g, " ")}</div></td><td>{m.tier}</td><td>{m.unit}</td>
                <td className="r">{edit?.sku === m.sku ? <><label className="sr-only" htmlFor="np">New price</label><input id="np" style={{ width: 100 }} inputMode="decimal" value={edit.price} onChange={(e) => setEdit({ sku: m.sku, price: e.target.value })} /></> : <Money value={m.unit_price} currency={m.currency} />}</td>
                <td>{m.lead_days} d</td>
                <td className="r">{admin && (edit?.sku === m.sku ? <><button className="quiet" onClick={save}>Save</button><button className="quiet" onClick={() => setEdit(null)}>Cancel</button></> : <button className="quiet" onClick={() => setEdit({ sku: m.sku, price: String(m.unit_price) })}>Edit</button>)}</td></tr>))}
            </tbody></table></div>)}
        </section>
        <div>
          <section className="panel"><h3>Labour rates (per hour)</h3>{cfg.data && <table className="ledger"><tbody>{cfg.data.labor_rates.map((r) => <tr key={r.trade}><td>{r.trade.replace(/_/g, " ")}</td><td className="r"><Money value={r.hourly_rate} /></td></tr>)}</tbody></table>}</section>
          <section className="panel"><h3>Regions</h3>{cfg.data && <table className="ledger"><tbody>{cfg.data.regions.map((r) => <tr key={r.key}><td>{r.name}</td><td className="r num">×{r.multiplier.toFixed(2)}</td></tr>)}</tbody></table>}</section>
        </div>
      </div>
    </Page>
  );
}
