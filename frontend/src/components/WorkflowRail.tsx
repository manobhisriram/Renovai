import type { WorkflowEvent } from "../types";

interface Props { steps: { node: string; label: string }[]; events: WorkflowEvent[]; labels: Record<string, string>; running: boolean }

/** The AI workflow drawn as a dimension line: one tick per step, line style shows state. No chain-of-thought is shown, only safe summaries. */
export function WorkflowRail({ steps, events, labels, running }: Props) {
  const byNode = new Map<string, WorkflowEvent>();
  for (const e of events) byNode.set(e.node.startsWith("plan_") ? "plan" : e.node, e);
  const extra = events.filter((e) => !steps.some((s) => s.node === (e.node.startsWith("plan_") ? "plan" : e.node)));
  const rows = [...steps.map((s) => ({ node: s.node, label: s.label, ev: byNode.get(s.node) })), ...extra.map((e) => ({ node: e.node, label: labels[e.node] ?? e.node, ev: e }))];
  const firstPending = rows.findIndex((r) => !r.ev);
  return (
    <ol className="dim" aria-label="AI workflow progress">
      {rows.map((r, i) => {
        const state = r.ev ? r.ev.status : "pending";
        const active = running && i === firstPending;
        return (
          <li key={r.node + i} className={state}>
            <div className="label">{r.label}{active && <> <span className="spinner" aria-label="in progress" /></>}
              {r.ev && <span className="ms">{state === "waiting" ? "waiting for a person" : state === "skipped" ? "skipped" : `${r.ev.latency_ms} ms`}</span>}
            </div>
            {r.ev && <div className="summary">{r.ev.summary}</div>}
          </li>
        );
      })}
    </ol>
  );
}
