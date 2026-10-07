import { Navigate, Route, Routes } from "react-router-dom";
import AppLayout from "./layouts/AppLayout";
import Analytics from "./pages/Analytics";
import Approvals from "./pages/Approvals";
import Crm from "./pages/Crm";
import Dashboard from "./pages/Dashboard";
import Knowledge from "./pages/Knowledge";
import Login from "./pages/Login";
import NewProject from "./pages/NewProject";
import PricingData from "./pages/PricingData";
import ProjectWorkspace from "./pages/ProjectWorkspace";
import Projects from "./pages/Projects";
import Settings from "./pages/Settings";
import { useAuth } from "./stores/auth";

export default function App() {
  const token = useAuth((s) => s.token);
  if (!token) return <Routes><Route path="*" element={<Login />} /></Routes>;
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<Dashboard />} />
        <Route path="projects" element={<Projects />} />
        <Route path="projects/new" element={<NewProject />} />
        <Route path="projects/:id/*" element={<ProjectWorkspace />} />
        <Route path="approvals" element={<Approvals />} />
        <Route path="crm" element={<Crm />} />
        <Route path="knowledge" element={<Knowledge />} />
        <Route path="pricing" element={<PricingData />} />
        <Route path="analytics" element={<Analytics />} />
        <Route path="settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
