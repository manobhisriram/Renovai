"""Retrieval: vector search -> metadata-aware rerank -> grounded, injection-safe context."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from app.config import Settings
from app.llm.safety import scan_injection, wrap_untrusted
from app.observability import metrics
from app.rag.store import Hit, VectorStore

_TOKEN = re.compile(r"[a-z0-9]+")


@dataclass
class Evidence:
    doc_id: str
    chunk_id: str
    title: str
    doc_type: str
    score: float
    snippet: str
    metadata: dict[str, Any] = field(default_factory=dict)
    flagged: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"doc_id": self.doc_id, "chunk_id": self.chunk_id, "title": self.title, "doc_type": self.doc_type,
                "score": round(self.score, 4), "snippet": self.snippet, "metadata": self.metadata, "flagged": self.flagged}


@dataclass
class RetrievalResult:
    query: str
    evidence: list[Evidence]
    context: str
    latency_ms: int
    degraded: str | None = None  # set when retrieval failed and the flow continued without evidence

    def ids(self) -> list[str]:
        return [e.doc_id for e in self.evidence]


class Retriever:
    def __init__(self, store: VectorStore, settings: Settings):
        self.store = store
        self.settings = settings

    @staticmethod
    def _lexical(query: str, text: str) -> float:
        q, t = set(_TOKEN.findall(query.lower())), set(_TOKEN.findall(text.lower()))
        return len(q & t) / len(q) if q else 0.0

    def rerank(self, query: str, hits: list[Hit], preferred: dict[str, Any] | None) -> list[Hit]:
        """Blend vector score with lexical overlap and a small boost for metadata that matches the project."""
        preferred = preferred or {}
        rescored = []
        for h in hits:
            boost = 0.0
            for key, weight in (("category", 0.10), ("room_type", 0.05), ("location", 0.05)):
                want = preferred.get(key)
                if want and str(h.payload.get(key, "")).lower() == str(want).lower():
                    boost += weight
            rescored.append((0.70 * h.score + 0.25 * self._lexical(query, h.text) + boost, h))
        rescored.sort(key=lambda x: x[0], reverse=True)
        return [Hit(h.id, round(score, 6), h.text, h.payload) for score, h in rescored]

    def retrieve(self, query: str, *, filters: dict[str, Any] | None = None, preferred: dict[str, Any] | None = None,
                 top_k: int | None = None) -> RetrievalResult:
        top_k = top_k or self.settings.rag_top_k
        start = time.perf_counter()
        try:
            hits = self.store.search(query, limit=self.settings.rag_candidate_k, filters=filters)
        except Exception as exc:  # degraded mode: continue without evidence, say so explicitly
            ms = int((time.perf_counter() - start) * 1000)
            return RetrievalResult(query, [], "", ms, degraded=f"Knowledge retrieval unavailable ({type(exc).__name__}).")
        hits = self.rerank(query, hits, preferred)[:top_k]
        evidence, parts, used = [], [], 0
        for h in hits:
            flags = scan_injection(h.text)
            title = str(h.payload.get("title") or h.text.split("\n", 1)[0])[:120]
            ev = Evidence(doc_id=h.doc_id, chunk_id=h.id, title=title, doc_type=str(h.payload.get("doc_type", "document")),
                          score=h.score, snippet=h.text[:420],
                          metadata={k: v for k, v in h.payload.items() if k not in ("text",)}, flagged=flags)
            evidence.append(ev)
            if flags:  # retrieved text that looks like an instruction never reaches the model
                continue
            block = wrap_untrusted("document", h.text, id=h.doc_id, type=ev.doc_type)
            if used + len(block) > self.settings.rag_context_max_chars:
                break
            parts.append(block)
            used += len(block)
        ms = int((time.perf_counter() - start) * 1000)
        metrics.RAG_LATENCY.observe(ms / 1000)
        return RetrievalResult(query, evidence, "\n".join(parts), ms)
