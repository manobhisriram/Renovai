import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ErrorNote, Loading, Money, Page, StatusPill } from "../components/ui";
import { usePolling } from "../hooks/usePolling";
import { api, errorMessage } from "../services/api";
import type { Project, Quote, QuoteSummary, WorkflowStatus } from "../types";
import { ChatTab } from "./project/ChatTab";
import { CrmTab } from "./project/CrmTab";
import { EvidenceTab } from "./project/EvidenceTab";
import { HistoryTab } from "./project/HistoryTab";
import { QuoteTab } from "./project/QuoteTab";
import { RequirementsTab } from "./project/RequirementsTab";
import { VisionTab } from "./project/VisionTab";
import { VisualizeTab } from "./project/VisualizeTab";
import { WorkflowTab } from "./project/WorkflowTab";

const TABS = [
  ["", "Workflow"], ["vision", "Photos and vision"], ["requirements", "Requirements"], ["evidence", "Evidence"], ["quote", "Quote"],
  ["history", "History"], ["chat", "Conversation"], ["visualize", "Renders"], ["crm", "CRM"],
] as const;

export default function ProjectWorkspace() {
  const { id = "", "*": sub = "" } = useParams();
  const nav = useNavigate();
  const [project, setProject] = useState<Project | null>(null);
  const [wf, setWf] = useState<WorkflowStatus | null>(null);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [quoteLoading, setQuoteLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [p, w] = await Promise.all([api.get<Project>(`/projects/${id}`), api.get<WorkflowStatus>(`/projects/${id}/workflow`)]);
      setProject(p); setWf(w); setError(null);
      if (p.current_quote_version > 0) {
        const list = await api.get<QuoteSummary[]>(`/projects/${id}/quotes`);
        const latest = list[0];
        if (latest) setQuote(await api.get<Quote>(`/projects/${id}/quotes/${latest.version}`));
      } else setQuote(null);
    } catch (e) { setError(errorMessage(e)); } finally { setQuoteLoading(false); }
  }, [id]);

  useEffect(() => { void refresh(); }, [refresh]);
  const running = wf?.run?.status === "running" || project?.status === "analyzing";
  usePolling(refresh, Boolean(running), 1500);

  const tab = TABS.some(([k]) => k === sub) ? sub : "";
  if (error && !project) return <Page title="Project"><ErrorNote message={error} onRetry={refresh} /></Page>;
  if (!project) return <Loading label="Loading project" />;

  return (
    <Page title={project.title} sub={<span className="row"><StatusPill status={project.status} /><span>{project.lead.name}</span>{project.category && <span className="faint">{project.category.replace(/_/g, " ")}</span>}
      {project.summary.total && <Money value={project.summary.total} currency={project.summary.currency} />}</span>}>
      <div className="tabs" role="tablist" aria-label="Project sections">
        {TABS.map(([k, label]) => <button key={k} role="tab" aria-selected={tab === k} onClick={() => nav(k ? `/projects/${id}/${k}` : `/projects/${id}`)}>{label}</button>)}
      </div>
      {error && <ErrorNote message={error} onRetry={refresh} />}
      {tab === "" && <WorkflowTab project={project} wf={wf} refresh={refresh} />}
      {tab === "vision" && <VisionTab projectId={id} onChanged={refresh} />}
      {tab === "requirements" && <RequirementsTab projectId={id} onChanged={refresh} />}
      {tab === "evidence" && <EvidenceTab quote={quote} />}
      {tab === "quote" && <QuoteTab project={project} quote={quote} loading={quoteLoading} refresh={refresh} />}
      {tab === "history" && <HistoryTab projectId={id} version={project.current_quote_version} />}
      {tab === "chat" && <ChatTab projectId={id} onChanged={refresh} />}
      {tab === "visualize" && <VisualizeTab projectId={id} />}
      {tab === "crm" && <CrmTab project={project} version={project.current_quote_version} />}
    </Page>
  );
}
