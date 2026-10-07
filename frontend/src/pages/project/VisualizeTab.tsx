import { useCallback, useState, type FormEvent } from "react";
import { AuthImage } from "../../components/AuthImage";
import { Empty, ErrorNote, Loading } from "../../components/ui";
import { useAsync } from "../../hooks/useAsync";
import { api, errorMessage } from "../../services/api";
import type { ImageMeta } from "../../types";

interface Visual { id: string; prompt: string; status: string; error: string | null; disclaimer: string }
interface VizList { enabled: boolean; provider: string; items: Visual[] }

export function VisualizeTab({ projectId }: { projectId: string }) {
  const fn = useCallback(() => api.get<VizList>(`/projects/${projectId}/visualizations`), [projectId]);
  const viz = useAsync(fn);
  const imgFn = useCallback(() => api.get<ImageMeta[]>(`/projects/${projectId}/images`), [projectId]);
  const images = useAsync(imgFn);
  const [prompt, setPrompt] = useState("");
  const [imageId, setImageId] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const go = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setErr(null);
    try { await api.post(`/projects/${projectId}/visualizations`, { prompt, image_id: imageId || null }); setPrompt(""); await viz.reload(); }
    catch (e2) { setErr(errorMessage(e2)); } finally { setBusy(false); }
  };
  if (viz.loading) return <Loading />;
  if (viz.error) return <ErrorNote message={viz.error} onRetry={viz.reload} />;
  return (
    <div className="split">
      <section className="panel"><h3>Illustrative renders</h3>
        <div className="callout"><strong>Not a drawing.</strong> Renders are AI illustrations to start a conversation. They are not construction-ready plans, and each image carries a notice saying so.</div>
        {viz.data?.items.filter((v) => v.status === "completed").length ? (
          <div className="cols">{viz.data.items.filter((v) => v.status === "completed").map((v) => (
            <figure key={v.id} style={{ margin: 0 }}><AuthImage path={`/projects/${projectId}/visualizations/${v.id}/content`} alt={`Render: ${v.prompt.slice(0, 80)}`} /><figcaption className="faint">{v.prompt.slice(0, 120)}</figcaption></figure>))}</div>
        ) : <Empty title="No renders yet">{viz.data?.enabled ? "Describe the look you want to see." : "Image generation is not configured on this server."}</Empty>}
      </section>
      <form className="panel" onSubmit={go} aria-label="Create a render">
        <h3>New render</h3>
        {!viz.data?.enabled && <div className="callout">Set VIZ_PROVIDER=openai_images and OPENAI_API_KEY on the server to turn this on.</div>}
        <div className="field"><label htmlFor="vp">What should it show?</label><textarea id="vp" value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="A modern minimalist version of this room" maxLength={600} /></div>
        <div className="field"><label htmlFor="vi">Based on photo (optional)</label>
          <select id="vi" value={imageId} onChange={(e) => setImageId(e.target.value)}><option value="">No photo; generate from the description</option>{images.data?.map((i) => <option key={i.id} value={i.id}>{i.filename}</option>)}</select></div>
        {err && <ErrorNote message={err} />}
        <button className="primary" disabled={busy || prompt.trim().length < 3 || !viz.data?.enabled}>{busy ? "Generating…" : "Generate render"}</button>
      </form>
    </div>
  );
}
