import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { ErrorNote, Loading } from "../../components/ui";
import { useAsync } from "../../hooks/useAsync";
import { api, errorMessage } from "../../services/api";
import type { Message } from "../../types";

export function ChatTab({ projectId, onChanged }: { projectId: string; onChanged: () => Promise<void> }) {
  const fn = useCallback(() => api.get<Message[]>(`/projects/${projectId}/messages`), [projectId]);
  const msgs = useAsync(fn);
  const [text, setText] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView?.({ block: "end" }); }, [msgs.data?.length]);

  const send = async (e: FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;
    setBusy(true); setErr(null);
    try { await api.post(`/projects/${projectId}/messages`, { content: text }); setText(""); await msgs.reload(); await onChanged(); }
    catch (e2) { setErr(errorMessage(e2)); } finally { setBusy(false); }
  };

  return (
    <section className="panel"><h3>Conversation with the client</h3>
      <p className="faint">Type what the client says. The assistant works out whether they are answering a question, pushing back on price, asking for changes, or asking for ideas.</p>
      {msgs.loading ? <Loading /> : msgs.error ? <ErrorNote message={msgs.error} onRetry={msgs.reload} /> : (
        <div className="chat" role="log" aria-live="polite">
          {msgs.data?.length === 0 && <p className="muted">No messages yet.</p>}
          {msgs.data?.map((m) => <div key={m.id} className={`bubble ${m.role}`}><span className="sr-only">{m.role}: </span>{m.content}</div>)}
          <div ref={end} />
        </div>)}
      <form onSubmit={send} className="row" style={{ marginTop: 14, alignItems: "flex-end" }} aria-label="Send a message">
        <div style={{ flex: 1, minWidth: 240 }}><label htmlFor="msg" className="sr-only">Message</label><textarea id="msg" style={{ minHeight: 56 }} value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. That is too expensive, my budget is 5 lakh" /></div>
        <button className="primary" disabled={busy || !text.trim()}>{busy ? "Sending…" : "Send"}</button>
      </form>
      {err && <ErrorNote message={err} />}
    </section>
  );
}
