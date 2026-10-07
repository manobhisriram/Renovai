import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ErrorNote, Page } from "../components/ui";
import { api, errorMessage } from "../services/api";
import type { ImageMeta, Project } from "../types";

const MAX_MB = 8;
const OK_TYPES = ["image/jpeg", "image/png", "image/webp"];

export default function NewProject() {
  const nav = useNavigate();
  const [f, setF] = useState({ name: "", email: "", phone: "", title: "", text: "", location: "", area: "" });
  const [files, setFiles] = useState<File[]>([]);
  const [fileErr, setFileErr] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  const pick = (list: FileList | null) => {
    setFileErr(null);
    const picked = Array.from(list ?? []);
    const bad = picked.find((x) => !OK_TYPES.includes(x.type) || x.size > MAX_MB * 1024 * 1024);
    if (bad) { setFileErr(`"${bad.name}" can't be used. Choose JPEG, PNG or WebP photos under ${MAX_MB} MB.`); return; }
    setFiles(picked);
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!f.text.trim() && files.length === 0) { setError("Describe the project or add at least one photo."); return; }
    try {
      setBusy("Creating project");
      const p = await api.post<Project>("/projects", {
        lead: { name: f.name, email: f.email || null, phone: f.phone || null }, title: f.title || `${f.name}: new project`,
        request_text: f.text, location: f.location || null, area_sqm: f.area ? Number(f.area) / 10.7639 : null,
      });
      if (files.length) {
        setBusy("Uploading photos");
        const form = new FormData();
        files.forEach((x) => form.append("files", x));
        await api.upload<ImageMeta[]>(`/projects/${p.id}/images`, form);
      }
      setBusy("Starting analysis");
      await api.post(`/projects/${p.id}/analyze`);
      nav(`/projects/${p.id}`);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(null);
    }
  };

  return (
    <Page title="New project" sub="Photos and a plain-language request are enough to start. The assistant will ask for anything that is missing.">
      <form onSubmit={submit} aria-label="New project">
        <div className="split">
          <div>
            <section className="panel"><h3>The request</h3>
              <div className="field"><label htmlFor="text">What does the client want?</label>
                <textarea id="text" value={f.text} onChange={set("text")} placeholder="e.g. A modern minimalist kitchen, budget around 8 lakh, finished in 6 weeks." maxLength={4000} />
                <div className="hint">Mention style, budget, timeline and size if the client gave them. Leave out what is unknown; do not guess.</div></div>
              <div className="cols">
                <div className="field"><label htmlFor="loc">City</label><input id="loc" value={f.location} onChange={set("location")} placeholder="Chennai" /></div>
                <div className="field"><label htmlFor="area">Floor area (sq ft)</label><input id="area" inputMode="decimal" pattern="[0-9]*\.?[0-9]*" value={f.area} onChange={set("area")} placeholder="Only if measured or stated" /></div>
              </div>
            </section>
            <section className="panel"><h3>Photos</h3>
              <div className="field"><label htmlFor="photos">Room photos</label><input id="photos" type="file" multiple accept={OK_TYPES.join(",")} onChange={(e) => pick(e.target.files)} />
                <div className="hint">Wide shots of each wall help. Photos cannot give exact measurements; the estimate will say so.</div>
                {fileErr && <div className="field-err" role="alert">{fileErr}</div>}
                {files.length > 0 && <div className="hint">{files.length} photo{files.length === 1 ? "" : "s"} selected.</div>}</div>
            </section>
          </div>
          <div>
            <section className="panel"><h3>The client</h3>
              <div className="field"><label htmlFor="name">Name</label><input id="name" required value={f.name} onChange={set("name")} /></div>
              <div className="field"><label htmlFor="em">Email</label><input id="em" type="email" value={f.email} onChange={set("email")} /><div className="hint">Used to recognise returning clients and recall their preferences.</div></div>
              <div className="field"><label htmlFor="ph">Phone</label><input id="ph" type="tel" value={f.phone} onChange={set("phone")} /></div>
              <div className="field"><label htmlFor="title">Project title</label><input id="title" value={f.title} onChange={set("title")} placeholder="Kitchen refit" /></div>
            </section>
            {error && <ErrorNote message={error} />}
            <button className="primary" disabled={busy !== null}>{busy ?? "Create and analyse"}</button>
          </div>
        </div>
      </form>
    </Page>
  );
}
