import { useCallback, useState, type FormEvent } from "react";
import { Empty, ErrorNote, Loading, Page } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { api, errorMessage } from "../services/api";
import { useAuth } from "../stores/auth";
import type { Evidence, KnowledgeDoc } from "../types";

const TYPES = ["past_project", "historical_quote", "specification", "material", "pricing", "contractor", "policy", "design_guideline", "faq", "customer_profile", "document"];

export default function Knowledge() {
  const admin = useAuth((s) => s.user?.role === "admin");
  const fn = useCallback(() => api.get<KnowledgeDoc[]>("/rag/documents"), []);
  const docs = useAsync(fn);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Evidence[] | null>(null);
  const [degraded, setDegraded] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [docType, setDocType] = useState("document");
  const [category, setCategory] = useState("");
  const [busy, setBusy] = useState(false);

  const search = async (e: FormEvent) => {
    e.preventDefault(); setErr(null);
    try { const r = await api.post<{ evidence: Evidence[]; degraded: string | null }>("/rag/search", { query: q, top_k: 6 }); setHits(r.evidence); setDegraded(r.degraded); }
    catch (e2) { setErr(errorMessage(e2)); }
  };
  const upload = async (e: FormEvent) => {
    e.preventDefault(); if (!file) return;
    setBusy(true); setErr(null);
    try { const form = new FormData(); form.append("file", file); form.append("doc_type", docType); if (category) form.append("category", category); await api.upload("/rag/documents", form); setFile(null); await docs.reload(); }
    catch (e2) { setErr(errorMessage(e2)); } finally { setBusy(false); }
  };
  const remove = async (id: string) => { try { await api.del(`/rag/documents/${id}`); await docs.reload(); } catch (e2) { setErr(errorMessage(e2)); } };

  return (
    <Page title="Knowledge base" sub="Past projects, quotes, materials, policies and client profiles the AI can cite. Uploaded text is treated as data, never as instructions.">
      {err && <ErrorNote message={err} />}
      <div className="split">
        <section className="panel"><h3>Documents</h3>
          {docs.loading ? <Loading /> : docs.error ? <ErrorNote message={docs.error} onRetry={docs.reload} /> : docs.data?.length ? (
            <table className="ledger"><thead><tr><th>Title</th><th>Type</th><th>Chunks</th><th /></tr></thead><tbody>
              {docs.data.map((d) => (<tr key={d.id}><td>{d.title}{d.is_sample && <> <span className="pill neutral">sample</span></>}<div className="faint">{d.id}</div></td><td>{d.doc_type.replace(/_/g, " ")}</td><td className="num">{d.chunk_count}</td>
                <td className="r">{admin && <button className="quiet danger" onClick={() => remove(d.id)} aria-label={`Delete ${d.title}`}>Delete</button>}</td></tr>))}
            </tbody></table>) : <Empty title="The knowledge base is empty">Run the seed script or upload documents so quotes can cite real projects.</Empty>}
        </section>
        <div>
          <form className="panel" onSubmit={search} aria-label="Test retrieval"><h3>Test a search</h3>
            <div className="field"><label htmlFor="rq">Query</label><input id="rq" value={q} onChange={(e) => setQ(e.target.value)} placeholder="modern kitchen Chennai quartz" /></div>
            <button disabled={q.trim().length < 2}>Search</button>
            {degraded && <div className="callout bad">{degraded}</div>}
            {hits && (hits.length ? <ul style={{ paddingLeft: 18 }}>{hits.map((h) => <li key={h.chunk_id}><strong>{h.title}</strong> <span className="faint">{h.score.toFixed(2)}</span></li>)}</ul> : <p className="muted">No matches.</p>)}
          </form>
          {admin ? (
            <form className="panel" onSubmit={upload} aria-label="Add a document"><h3>Add a document</h3>
              <div className="field"><label htmlFor="df">File (.md, .txt, .json, .pdf)</label><input id="df" type="file" accept=".md,.txt,.json,.pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></div>
              <div className="field"><label htmlFor="dt">Type</label><select id="dt" value={docType} onChange={(e) => setDocType(e.target.value)}>{TYPES.map((t) => <option key={t} value={t}>{t.replace(/_/g, " ")}</option>)}</select></div>
              <div className="field"><label htmlFor="dc">Category (optional)</label><input id="dc" value={category} onChange={(e) => setCategory(e.target.value)} placeholder="kitchen_renovation" /></div>
              <button className="primary" disabled={!file || busy}>{busy ? "Adding…" : "Add to knowledge base"}</button>
            </form>) : <p className="faint">Only administrators can add or remove documents.</p>}
        </div>
      </div>
    </Page>
  );
}
