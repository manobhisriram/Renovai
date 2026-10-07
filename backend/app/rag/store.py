"""Qdrant vector store wrapper (remote, embedded-local, or in-memory)."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from qdrant_client import QdrantClient, models

from app.config import ConfigurationError, Settings
from app.rag.chunking import Chunk
from app.rag.embeddings import Embedder
from app.utils.errors import ExternalServiceError
from app.utils.resilience import retry_call

log = logging.getLogger(__name__)
_NS = uuid.UUID("6f1d2c64-3d3e-4c4e-9f7a-0d6a8d1b9a10")
KEYWORD_FIELDS = ("doc_type", "category", "room_type", "location", "customer_email", "material_type", "doc_id", "project_id")


@dataclass
class Hit:
    id: str
    score: float
    text: str
    payload: dict[str, Any]

    @property
    def doc_id(self) -> str:
        return str(self.payload.get("doc_id", ""))


def point_id(doc_id: str, index: int) -> str:
    return str(uuid.uuid5(_NS, f"{doc_id}:{index}"))


def make_client(settings: Settings, *, in_memory: bool = False) -> QdrantClient:
    if in_memory:
        return QdrantClient(location=":memory:")
    if settings.qdrant_url:
        key = settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None
        return QdrantClient(url=settings.qdrant_url, api_key=key, timeout=15)
    if settings.is_production:
        raise ConfigurationError("QDRANT_URL is required in production (embedded local mode is for development only).")
    return QdrantClient(path=settings.qdrant_local_path)


class VectorStore:
    def __init__(self, client: QdrantClient, embedder: Embedder, collection: str):
        self.client = client
        self.embedder = embedder
        self.collection = collection
        self._remote = type(getattr(client, "_client", None)).__name__ == "QdrantRemote"

    def ensure_collection(self) -> None:
        """Create the collection if needed; raise ConfigurationError on a vector-dimension mismatch."""

        def _fetch() -> int | None:
            existing = {c.name for c in self.client.get_collections().collections}
            if self.collection not in existing:
                return None
            info = self.client.get_collection(self.collection)
            return int(info.config.params.vectors.size)  # type: ignore[union-attr]

        try:
            size = retry_call(_fetch, attempts=3, base_delay=0.3)
        except Exception as exc:
            raise ExternalServiceError(f"Vector database is unavailable: {type(exc).__name__}") from exc
        if size is not None:
            if size != self.embedder.dim:
                raise ConfigurationError(
                    f"Qdrant collection '{self.collection}' has {size}-dim vectors but embedder '{self.embedder.name}' "
                    f"produces {self.embedder.dim}. Use a new QDRANT_COLLECTION or re-ingest (scripts/seed.py --reset-knowledge)."
                )
            return
        try:
            self.client.create_collection(
                self.collection,
                vectors_config=models.VectorParams(size=self.embedder.dim, distance=models.Distance.COSINE),
            )
            if self._remote:
                for f in KEYWORD_FIELDS:
                    self.client.create_payload_index(self.collection, f, models.PayloadSchemaType.KEYWORD)
        except Exception as exc:
            raise ExternalServiceError(f"Could not create vector collection: {type(exc).__name__}") from exc

    def upsert(self, chunks: list[Chunk]) -> int:
        if not chunks:
            return 0
        vectors = self.embedder.embed([c.text for c in chunks])
        points = [
            models.PointStruct(
                id=point_id(c.doc_id, c.index), vector=v,
                payload={**{k: val for k, val in c.metadata.items() if isinstance(val, (str, int, float, bool, list))},
                         "doc_id": c.doc_id, "chunk_index": c.index, "text": c.text},
            )
            for c, v in zip(chunks, vectors, strict=True)
        ]
        try:
            self.client.upsert(self.collection, points=points, wait=True)
        except Exception as exc:
            raise ExternalServiceError(f"Vector database write failed: {type(exc).__name__}") from exc
        return len(points)

    def delete_doc(self, doc_id: str) -> None:
        self.client.delete(
            self.collection,
            points_selector=models.FilterSelector(filter=models.Filter(must=[
                models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))])),
        )

    @staticmethod
    def _filter(filters: dict[str, Any] | None) -> models.Filter | None:
        if not filters:
            return None
        must = []
        for key, value in filters.items():
            if value in (None, "", []):
                continue
            cond = models.MatchAny(any=list(value)) if isinstance(value, (list, tuple, set)) else models.MatchValue(value=value)
            must.append(models.FieldCondition(key=key, match=cond))
        return models.Filter(must=must) if must else None

    def search(self, query: str, *, limit: int, filters: dict[str, Any] | None = None) -> list[Hit]:
        vector = self.embedder.embed([query])[0]
        try:
            res = self.client.query_points(self.collection, query=vector, limit=limit, query_filter=self._filter(filters), with_payload=True)
        except Exception as exc:
            raise ExternalServiceError(f"Vector search failed: {type(exc).__name__}") from exc
        return [Hit(id=str(p.id), score=float(p.score), text=str((p.payload or {}).get("text", "")), payload=dict(p.payload or {})) for p in res.points]

    def count(self) -> int:
        return int(self.client.count(self.collection, exact=True).count)

    def healthy(self) -> bool:
        try:
            self.client.get_collections()
            return True
        except Exception:
            return False
