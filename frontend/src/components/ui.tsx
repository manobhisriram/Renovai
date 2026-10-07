import type { ReactNode } from "react";
import type { Provenance } from "../types";

const PROV_LABEL: Record<Provenance, string> = { detected: "Detected", estimated: "Estimated", user_provided: "Provided by client", unknown: "Unknown" };
const PROV_HELP: Record<Provenance, string> = {
  detected: "Clearly visible or stated", estimated: "Inferred; not measured", user_provided: "Stated by the client or staff", unknown: "Could not be determined",
};

export function Provenance({ kind }: { kind: Provenance | undefined }) {
  const k = kind ?? "unknown";
  return <span className={`prov ${k}`} title={PROV_HELP[k]}>{PROV_LABEL[k]}</span>;
}

export function ProvenanceLegend() {
  return (
    <div className="legend" aria-label="How to read data labels">
      {(Object.keys(PROV_LABEL) as Provenance[]).map((k) => <span key={k}><Provenance kind={k} /> <span className="faint">{PROV_HELP[k]}</span></span>)}
    </div>
  );
}

export function Money({ value, currency = "INR", compact = false }: { value: number | null | undefined; currency?: string; compact?: boolean }) {
  if (value === null || value === undefined) return <span className="faint">n/a</span>;
  const f = new Intl.NumberFormat("en-IN", { style: "currency", currency, maximumFractionDigits: 0, notation: compact ? "compact" : "standard" });
  return <span className="num">{f.format(value)}</span>;
}

const STATUS_TONE: Record<string, string> = {
  approved: "ok", completed: "ok", synced: "ok", done: "ok", pending_approval: "warn", awaiting_approval: "warn", awaiting_clarification: "warn", waiting: "warn",
  pending: "warn", running: "info", analyzing: "info", draft: "neutral", rejected: "bad", failed: "bad", superseded: "neutral", open: "info",
};
export function StatusPill({ status }: { status: string }) {
  return <span className={`pill ${STATUS_TONE[status] ?? "neutral"}`}>{status.replace(/_/g, " ")}</span>;
}

export function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return <div className="empty"><h3>{title}</h3>{children && <p style={{ margin: "0 auto 12px" }}>{children}</p>}{action}</div>;
}

export function ErrorNote({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="callout bad" role="alert">
      <strong>That didn't work.</strong> {message} {onRetry && <button className="quiet" onClick={onRetry}>Try again</button>}
    </div>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return <p className="muted" role="status"><span className="spinner" aria-hidden /> {label}…</p>;
}

export function MockBanner({ show }: { show: boolean | undefined }) {
  if (!show) return null;
  return <div className="mock-banner" role="note"><strong>Mock AI is active.</strong> Text and photo analysis come from a deterministic test double, not a language model. Set LLM_PROVIDER=anthropic and an API key for real analysis.</div>;
}

export function Confidence({ value }: { value: number | undefined }) {
  if (value === undefined || value === null) return null;
  const tone = value >= 0.75 ? "ok" : value >= 0.5 ? "warn" : "bad";
  return <span className={`pill ${tone}`} title="Model and validation confidence, 0 to 1">confidence {value.toFixed(2)}</span>;
}

export function Page({ title, sub, actions, children }: { title: string; sub?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return (
    <>
      <header className="page-head"><div><h1>{title}</h1>{sub && <div className="sub">{sub}</div>}</div>{actions && <div className="row">{actions}</div>}</header>
      {children}
    </>
  );
}
