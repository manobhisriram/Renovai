import { useState } from "react";
import { Link } from "react-router-dom";
import { Empty, ErrorNote, Loading, StatusPill } from "../../components/ui";
import { WorkflowRail } from "../../components/WorkflowRail";
import { api, errorMessage } from "../../services/api";
import type { Project, WorkflowStatus } from "../../types";

export function WorkflowTab({ project, wf, refresh }: { project: Project; wf: WorkflowStatus | null; refresh: () => Promise<void> }) {
  const [answer, setAnswer] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (!wf) return <Loading label="Loading workflow" />;
  const run = wf.run;
  const wait = run?.status === "waiting" ? run.waiting_for : null;

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true); setErr(null);
    try { await fn(); setAnswer(""); await refresh(); } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  };

  return (
    <div className="split">
      <section className="panel" aria-labelledby="wf-h">
        <div className="spread"><h3 id="wf-h">AI workflow</h3>{run && <StatusPill status={run.status} />}</div>
        {!run ? <Empty title="Not analysed yet" action={<button className="primary" disabled={busy} onClick={() => act(() => api.post(`/projects/${project.id}/analyze`))}>Run analysis</button>}>
          The workflow reads photos, extracts requirements, retrieves similar projects, prices the work and prepares a quote for approval.</Empty> :
          <WorkflowRail steps={wf.steps} events={wf.events} labels={wf.labels} running={run.status === "running"} />}
        {run?.status === "failed" && <ErrorNote message={run.error ?? "The analysis failed."} onRetry={() => act(() => api.post(`/projects/${project.id}/analyze`))} />}
        {err && <ErrorNote message={err} />}
      </section>

      <aside>
        {wait?.type === "clarification" && (
          <section className="panel" aria-labelledby="cl-h">
            <h3 id="cl-h">The client needs to answer</h3>
            <ul>{wait.questions?.map((q, i) => <li key={i}>{q}</li>)}</ul>
            <label htmlFor="ans">Their reply</label>
            <textarea id="ans" value={answer} onChange={(e) => setAnswer(e.target.value)} placeholder="Paste or type the client's answer" />
            <div className="row"><button className="primary" disabled={busy || !answer.trim()} onClick={() => act(() => api.post(`/projects/${project.id}/clarifications`, { answer }))}>Send reply</button>
              <button onClick={() => act(() => api.post(`/projects/${project.id}/workflow/cancel`))} disabled={busy}>Cancel workflow</button></div>
            <p className="faint">If the questions stay unanswered, the estimate continues with clearly flagged assumptions.</p>
          </section>)}
        {wait?.type === "approval" && (
          <section className="panel"><h3>Ready for review</h3>
            <p>The quote is waiting for a reviewer. Nothing is written to the CRM until it is approved.</p>
            <Link className="btn primary" to={`/projects/${project.id}/quote`}>Open the quote</Link></section>)}
        {run?.status === "completed" && project.status === "approved" && <div className="callout ok">Approved. The lead has been handed to the CRM; check the CRM tab for the sync result.</div>}
        {project.suspicious_input && <div className="callout bad" role="alert"><strong>Review the client text.</strong> It matched patterns used to manipulate AI systems. It was treated as data only, and a person must approve the quote.</div>}
      </aside>
    </div>
  );
}
