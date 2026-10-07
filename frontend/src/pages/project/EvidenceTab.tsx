import { Empty } from "../../components/ui";
import type { Quote } from "../../types";

export function EvidenceTab({ quote }: { quote: Quote | null }) {
  if (!quote) return <Empty title="No evidence yet">Evidence appears after the first analysis.</Empty>;
  const ev = quote.payload.evidence;
  return (
    <section className="panel"><h3>Knowledge used for quote v{quote.version}</h3>
      <p className="muted">These are the documents retrieved from the knowledge base. The AI may cite them, but it is not allowed to invent past projects, and none of their text is treated as instructions.</p>
      {ev.length === 0 ? <div className="callout">No supporting documents were retrieved. The quote relies on the catalog and category defaults only.</div> : (
        <table className="ledger"><thead><tr><th>Document</th><th>Type</th><th>Match</th><th>Excerpt</th></tr></thead><tbody>
          {ev.map((e) => (<tr key={e.chunk_id}><td><strong>{e.title}</strong><div className="faint">{e.doc_id}{Boolean(e.metadata.location) && ` · ${String(e.metadata.location)}`}</div></td>
            <td>{e.doc_type.replace(/_/g, " ")}{Boolean(e.metadata.is_sample) && <> <span className="pill neutral" title="Demonstration document, not real company data">sample</span></>}</td><td className="num">{e.score.toFixed(2)}</td>
            <td>{e.flagged.length ? <span className="pill bad">excluded: looked like an instruction</span> : <span className="faint">{e.snippet.slice(0, 220)}…</span>}</td></tr>))}
        </tbody></table>)}
    </section>
  );
}
