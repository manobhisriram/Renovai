import { useCallback, useState, type FormEvent } from "react";
import { ErrorNote, Loading, Provenance, ProvenanceLegend, Confidence } from "../../components/ui";
import { useAsync } from "../../hooks/useAsync";
import { api, errorMessage } from "../../services/api";
import type { Requirements } from "../../types";

export function RequirementsTab({ projectId, onChanged }: { projectId: string; onChanged: () => void }) {
  const fn = useCallback(() => api.get<{ requirements: Requirements | null }>(`/projects/${projectId}/requirements`), [projectId]);
  const r = useAsync(fn);
  const [f, setF] = useState({ area: "", location: "", style: "", budget: "", weeks: "" });
  const [err, setErr] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const req = r.data?.requirements;
  const P = req?.provenance ?? {};

  const save = async (e: FormEvent) => {
    e.preventDefault(); setErr(null); setSaved(false);
    const body: Record<string, unknown> = {};
    if (f.area) body.area_sqm = Number(f.area) / 10.7639;
    if (f.location) body.location = f.location;
    if (f.style) body.desired_style = f.style;
    if (f.budget) body.budget_amount = Number(f.budget);
    if (f.weeks) body.timeline_weeks = Number(f.weeks);
    if (!Object.keys(body).length) { setErr("Enter at least one value to save."); return; }
    try { await api.patch(`/projects/${projectId}/requirements`, body); setF({ area: "", location: "", style: "", budget: "", weeks: "" }); setSaved(true); await r.reload(); onChanged(); }
    catch (e2) { setErr(errorMessage(e2)); }
  };

  if (r.loading) return <Loading />;
  if (r.error) return <ErrorNote message={r.error} onRetry={r.reload} />;
  const rows: [string, string | number | null | undefined, string][] = [
    ["Project type", req?.project_type, "project_type"], ["Property", req?.property_type, "property_type"], ["Style", req?.desired_style, "desired_style"],
    ["Budget", req?.budget ? `${req.budget.currency} ${req.budget.amount.toLocaleString("en-IN")}` : null, "budget"],
    ["Timeline", req?.timeline_weeks ? `${req.timeline_weeks} weeks` : null, "timeline_weeks"], ["Floor area", req?.area_sqm ? `${req.area_sqm.toFixed(1)} sqm` : null, "area_sqm"],
    ["Location", req?.location, "location"], ["Rooms", req?.rooms?.join(", "), "rooms"],
  ];
  return (
    <div className="split">
      <section className="panel"><div className="spread"><h3>Requirements</h3><Confidence value={req?.confidence} /></div>
        {!req ? <p className="muted">Nothing extracted yet. Run the analysis from the Workflow tab.</p> : (
          <>
            <ProvenanceLegend />
            <table className="ledger" style={{ marginTop: 10 }}><tbody>{rows.map(([label, value, key]) => (
              <tr key={key}><td style={{ width: 140 }}>{label}</td><td>{value ?? <span className="faint">not provided</span>}</td><td><Provenance kind={value ? P[key] ?? "estimated" : "unknown"} /></td></tr>))}
              {(req.must_haves?.length ?? 0) > 0 && <tr><td>Must have</td><td colSpan={2}>{req.must_haves?.join("; ")}</td></tr>}
              {(req.constraints?.length ?? 0) > 0 && <tr><td>Constraints</td><td colSpan={2}>{req.constraints?.join("; ")}</td></tr>}
            </tbody></table>
            {req.vision_area_hint_sqm && <div className="callout">Photos suggest roughly {req.vision_area_hint_sqm} sqm. That is an unverified estimate and is not used as the area until someone confirms it.</div>}
            {(req.missing_information?.length ?? 0) > 0 && <p className="muted">Still unknown: {req.missing_information?.map((m) => m.replace(/_/g, " ")).join(", ")}.</p>}
          </>)}
      </section>
      <form className="panel" onSubmit={save} aria-label="Edit requirements">
        <h3>Confirm or correct</h3>
        <p className="faint">Values entered here are recorded as provided by the client or staff. Re-run the analysis to update the quote.</p>
        <div className="field"><label htmlFor="a">Floor area (sq ft)</label><input id="a" inputMode="decimal" value={f.area} onChange={(e) => setF({ ...f, area: e.target.value })} /></div>
        <div className="field"><label htmlFor="l">City</label><input id="l" value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })} /></div>
        <div className="field"><label htmlFor="s">Style</label><input id="s" value={f.style} onChange={(e) => setF({ ...f, style: e.target.value })} /></div>
        <div className="field"><label htmlFor="b">Budget (INR)</label><input id="b" inputMode="numeric" value={f.budget} onChange={(e) => setF({ ...f, budget: e.target.value })} /></div>
        <div className="field"><label htmlFor="w">Timeline (weeks)</label><input id="w" inputMode="decimal" value={f.weeks} onChange={(e) => setF({ ...f, weeks: e.target.value })} /></div>
        {err && <div className="field-err" role="alert">{err}</div>}{saved && <div className="callout ok" role="status">Saved.</div>}
        <button className="primary">Save changes</button>
      </form>
    </div>
  );
}
