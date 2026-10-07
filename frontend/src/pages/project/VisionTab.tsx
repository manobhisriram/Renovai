import { useCallback, useRef, useState } from "react";
import { AuthImage } from "../../components/AuthImage";
import { Empty, ErrorNote, Loading, Provenance, ProvenanceLegend } from "../../components/ui";
import { Feedback } from "../../components/Feedback";
import { useAsync } from "../../hooks/useAsync";
import { api, errorMessage } from "../../services/api";
import type { Attribute, ImageMeta, VisionResponse } from "../../types";

function Attr({ label, a }: { label: string; a: Attribute }) {
  return <tr><td>{label}</td><td>{a.value ?? <span className="faint">not determined</span>}</td><td><Provenance kind={a.provenance} /></td><td className="r num">{a.confidence ? a.confidence.toFixed(2) : "–"}</td></tr>;
}

export function VisionTab({ projectId, onChanged }: { projectId: string; onChanged: () => void }) {
  const imgFn = useCallback(() => api.get<ImageMeta[]>(`/projects/${projectId}/images`), [projectId]);
  const images = useAsync(imgFn);
  const vFn = useCallback(() => api.get<VisionResponse>(`/projects/${projectId}/vision`), [projectId]);
  const vision = useAsync(vFn);
  const input = useRef<HTMLInputElement>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy(true); setErr(null);
    try {
      const form = new FormData();
      Array.from(files).forEach((f) => form.append("files", f));
      await api.upload(`/projects/${projectId}/images`, form);
      await images.reload(); onChanged();
    } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); if (input.current) input.current.value = ""; }
  };
  const remove = async (id: string) => {
    try { await api.del(`/projects/${projectId}/images/${id}`); await images.reload(); await vision.reload(); onChanged(); } catch (e) { setErr(errorMessage(e)); }
  };

  return (
    <div className="stack">
      <section className="panel"><div className="spread"><h3>Photos</h3>
        <div><label htmlFor="more" className="sr-only">Add photos</label><input id="more" ref={input} type="file" multiple accept="image/jpeg,image/png,image/webp" onChange={(e) => upload(e.target.files)} disabled={busy} /></div></div>
        {err && <ErrorNote message={err} />}
        {images.loading ? <Loading /> : images.data?.length ? (
          <div className="cols" style={{ gridTemplateColumns: "repeat(auto-fill,minmax(180px,1fr))" }}>
            {images.data.map((i) => (<figure key={i.id} style={{ margin: 0 }}><AuthImage path={`/projects/${projectId}/images/${i.id}/content`} alt={i.filename} />
              <figcaption className="faint">{i.filename} · {i.width}×{i.height} <button className="quiet danger" onClick={() => remove(i.id)} aria-label={`Remove ${i.filename}`}>Remove</button></figcaption></figure>))}
          </div>) : <Empty title="No photos">Add photos and run the analysis again to get a room read-out.</Empty>}
        <p className="faint">Re-run the analysis after adding or removing photos.</p>
      </section>

      <section className="panel"><h3>What the AI read from the photos</h3><ProvenanceLegend />
        {vision.loading ? <Loading /> : !vision.data?.items.length ? <p className="muted">No photo analysis yet.</p> : vision.data.items.map((it) => {
          const a = it.analysis;
          const d = a.dimensions;
          return (
            <div key={it.image_id} className="split" style={{ marginTop: 18, borderTop: "1px solid var(--rule)", paddingTop: 14 }}>
              <div><AuthImage path={`/projects/${projectId}/images/${it.image_id}/content`} alt="Analysed photo" />
                <p className="faint" style={{ marginTop: 6 }}>Measured from pixels ({it.cv.detector === "none" ? "no object detector configured" : it.cv.detector}): {it.cv.width}×{it.cv.height}, {it.cv.color_temperature} light, brightness {it.cv.brightness}.
                  {it.cv.quality_flags.length > 0 && <> Quality notes: {it.cv.quality_flags.join(", ").replace(/_/g, " ")}.</>}</p>
                <div className="row">{it.cv.palette.map((c) => <span key={c.hex} className="swatch" style={{ background: c.hex }} title={`${c.hex} · ${Math.round(c.share * 100)}%`} />)}</div></div>
              <div>
                <table className="ledger"><thead><tr><th>Attribute</th><th>Value</th><th>How known</th><th className="r">Conf.</th></tr></thead><tbody>
                  <Attr label="Room" a={a.room_type} /><Attr label="Style" a={a.design_style} /><Attr label="Flooring" a={a.flooring} /><Attr label="Walls" a={a.walls} />
                  <Attr label="Ceiling" a={a.ceiling} /><Attr label="Lighting" a={a.lighting} />
                  <tr><td>Size</td><td>{d.area_sqm ? `about ${d.area_sqm} sqm` : <span className="faint">not determined</span>}</td><td><Provenance kind={d.provenance} /></td><td className="r num">{d.confidence ? d.confidence.toFixed(2) : "–"}</td></tr>
                </tbody></table>
                {a.visible_issues.length > 0 && <><h4 style={{ marginTop: 12 }}>Visible issues</h4><ul>{a.visible_issues.map((v, i) => <li key={i}>{v.description} <span className="pill warn">{v.severity}</span></li>)}</ul></>}
                {a.renovation_opportunities.length > 0 && <><h4 style={{ marginTop: 12 }}>Opportunities</h4><ul>{a.renovation_opportunities.map((v, i) => <li key={i}>{v}</li>)}</ul></>}
                <div className="callout"><strong>Limits.</strong> <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>{a.limitations.map((l, i) => <li key={i}>{l}</li>)}</ul></div>
              </div>
            </div>);
        })}
        {vision.error && <ErrorNote message={vision.error} onRetry={vision.reload} />}
        <Feedback projectId={projectId} step="vision" />
      </section>
    </div>
  );
}
