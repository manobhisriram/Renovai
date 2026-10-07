import { useCallback, useEffect } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { MockBanner } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { usePolling } from "../hooks/usePolling";
import { api } from "../services/api";
import { useAuth } from "../stores/auth";
import type { Approval, SystemConfig } from "../types";

const NAV: { to: string; label: string; end?: boolean; group?: string }[] = [
  { to: "/", label: "Dashboard", end: true, group: "Work" },
  { to: "/projects", label: "Projects" },
  { to: "/projects/new", label: "New project" },
  { to: "/approvals", label: "Approvals" },
  { to: "/crm", label: "Leads and CRM", group: "Follow-up" },
  { to: "/knowledge", label: "Knowledge base", group: "AI inputs" },
  { to: "/pricing", label: "Pricing data" },
  { to: "/analytics", label: "Analytics", group: "Insight" },
  { to: "/settings", label: "Settings" },
];

export default function AppLayout() {
  const user = useAuth((s) => s.user);
  const signOut = useAuth((s) => s.signOut);
  const cfgFn = useCallback(() => api.get<SystemConfig>("/system/config"), []);
  const cfg = useAsync(cfgFn);
  const pendFn = useCallback(() => api.get<Approval[]>("/approvals?status=pending"), []);
  const pending = useAsync(pendFn);
  usePolling(() => pending.reload(), true, 20000);
  useEffect(() => { document.title = "RenovAI · Estimating desk"; }, []);

  return (
    <div className="shell">
      <aside className="rail">
        <div className="brand"><i aria-hidden /> RenovAI</div>
        <nav aria-label="Main">
          {NAV.map((n) => (
            <div key={n.to}>
              {n.group && <div className="group">{n.group}</div>}
              <NavLink to={n.to} end={n.end} className={({ isActive }) => `nav${isActive ? " active" : ""}`}>
                <span>{n.label}</span>
                {n.to === "/approvals" && (pending.data?.length ?? 0) > 0 && <span className="badge-count" aria-label={`${pending.data?.length} waiting`}>{pending.data?.length}</span>}
              </NavLink>
            </div>
          ))}
        </nav>
        <div className="who">
          <div>{user?.full_name}</div>
          <div className="faint" style={{ color: "#98aca6" }}>{user?.role}</div>
          <button onClick={signOut}>Sign out</button>
        </div>
      </aside>
      <main>
        <MockBanner show={cfg.data?.mock_ai} />
        <Outlet />
      </main>
    </div>
  );
}
