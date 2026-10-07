import { useEffect, useState, type FormEvent } from "react";
import { Empty, ErrorNote, Loading } from "../../components/ui";
import { Feedback } from "../../components/Feedback";
import { QuoteView } from "../../components/QuoteView";
import { api, errorMessage } from "../../services/api";
import { useAuth } from "../../stores/auth";
import type { Approval, Project, Quote, Tier } from "../../types";

export function QuoteTab({ project, quote, loading, refresh }: { project: Project; quote: Quote | null; loading: boolean; refresh: () => Promise<void> }) {
  const role = useAuth((s) => s.user?.role);
  const [tier, setTier] = useState<Tier>("standard");
  const [note, setNote] = useState("");
  const [budget, setBudget] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (quote) setTier(quote.selected_tier); }, [quote?.id, quote?.selected_tier]); // eslint-disable-line react-hooks/exhaustive-deps

  if (loading) return <Loading />;
  if (!quote) return <Empty title="No quote yet">Run the analysis from the Workflow tab to generate one.</Empty>;
  const approval: Approval | null | undefined = project.pending_approval;
  const canDecide = (role === "admin" || role === "reviewer") && approval?.status === "pending" && quote.status === "pending_approval";

  const act = async (fn: () => Promise<unknown>) => { setBusy(true); setErr(null); try { await fn(); await refresh(); } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); } };
  const decide = (decision: "approved" | "rejected") => act(() => api.post(`/approvals/${approval!.id}/decision`, { decision, note: note || null, selected_tier: decision === "approved" ? tier : null }));
  const revise = (e: FormEvent) => { e.preventDefault(); void act(async () => { await api.post(`/projects/${project.id}/quotes/revise`, { budget: budget ? Number(budget) : null, message: msg }); setBudget(""); setMsg(""); }); };

  return (
    <div className="split">
      <QuoteView quote={quote} tier={tier} onTier={setTier} />
      <aside>
        {canDecide && approval && (
          <section className="panel" aria-labelledby="ap-h"><h3 id="ap-h">Your decision</h3>
            <p className="muted">Why this needs a person:</p><ul>{approval.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
            <p>Approving sends <strong>{tier}</strong> to the client and writes the lead to the CRM.</p>
            <label htmlFor="note">Note (optional)</label><textarea id="note" value={note} onChange={(e) => setNote(e.target.value)} />
            <div className="row" style={{ marginTop: 10 }}><button className="primary" disabled={busy} onClick={() => decide("approved")}>Approve {tier}</button><button className="danger" disabled={busy} onClick={() => decide("rejected")}>Reject</button></div>
          </section>)}
        {quote.status === "pending_approval" && !canDecide && <div className="callout">Waiting for a reviewer or administrator to approve this version.</div>}
        <form className="panel" onSubmit={revise} aria-label="Revise the quote">
          <h3>Client says it is too expensive?</h3>
          <p className="faint">Enter their budget. The engine downgrades materials and drops optional items one step at a time, then lists every trade-off. The current version stays in the history.</p>
          <div className="field"><label htmlFor="rb">Target budget (INR)</label><input id="rb" inputMode="numeric" value={budget} onChange={(e) => setBudget(e.target.value)} placeholder="700000" /></div>
          <div className="field"><label htmlFor="rm">What must stay, or can go? (optional)</label><textarea id="rm" value={msg} onChange={(e) => setMsg(e.target.value)} placeholder="Keep the cabinets. We can skip the backsplash." /></div>
          <button disabled={busy || (!budget && !msg.trim())}>Create revised version</button>
        </form>
        {quote.payload.recommendations.length > 0 && (
          <section className="panel"><h3>Ideas to discuss</h3><ul>{quote.payload.recommendations.map((r, i) => <li key={i}><strong>{r.title}.</strong> {r.detail}</li>)}</ul></section>)}
        {err && <ErrorNote message={err} />}
        <Feedback projectId={project.id} step="quote" />
      </aside>
    </div>
  );
}
