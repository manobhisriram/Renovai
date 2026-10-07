import { useState } from "react";
import { api } from "../services/api";

export function Feedback({ projectId, step, label = "Was this helpful?" }: { projectId: string; step: string; label?: string }) {
  const [sent, setSent] = useState<1 | -1 | null>(null);
  const send = async (rating: 1 | -1) => {
    setSent(rating);
    try { await api.post(`/projects/${projectId}/feedback`, { step, rating }); } catch { setSent(null); }
  };
  return (
    <div className="row faint" role="group" aria-label={label}>
      <span>{sent ? "Thanks, noted." : label}</span>
      {!sent && <><button className="quiet" onClick={() => send(1)} aria-label="Yes, helpful">Yes</button><button className="quiet" onClick={() => send(-1)} aria-label="No, not helpful">No</button></>}
    </div>
  );
}
