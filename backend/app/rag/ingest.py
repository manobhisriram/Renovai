"""Document ingestion: parse -> chunk -> embed -> upsert into Qdrant + register in the relational DB."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.database.models import KnowledgeDoc
from app.rag.chunking import chunk_document, content_hash, parse_document
from app.rag.store import VectorStore
from app.utils.errors import ValidationFailed

ALLOWED_SUFFIXES = (".md", ".txt", ".json", ".pdf")
MAX_DOC_BYTES = 5 * 1024 * 1024
DOC_TYPES = {"past_project", "specification", "material", "pricing", "contractor", "policy", "design_guideline", "faq",
             "historical_quote", "customer_profile", "document"}


def doc_id_for(filename: str, metadata: dict[str, Any]) -> str:
    explicit = metadata.get("doc_id")
    if explicit:
        return re.sub(r"[^a-zA-Z0-9_.\-]", "_", str(explicit))[:64]
    return hashlib.sha1(filename.encode(), usedforsecurity=False).hexdigest()[:16]


def ingest_bytes(*, session: Session, store: VectorStore, settings: Settings, filename: str, data: bytes,
                 metadata: dict[str, Any] | None = None, is_sample: bool = False) -> KnowledgeDoc:
    if not filename.lower().endswith(ALLOWED_SUFFIXES):
        raise ValidationFailed(f"Unsupported document type. Allowed: {', '.join(ALLOWED_SUFFIXES)}")
    if len(data) > MAX_DOC_BYTES:
        raise ValidationFailed("Document exceeds the 5 MB limit.")
    parsed = parse_document(Path(filename).name, data, metadata)
    if not parsed.text:
        raise ValidationFailed("The document contains no extractable text.")
    meta = dict(parsed.metadata)
    doc_type = str(meta.get("doc_type", "document"))
    if doc_type not in DOC_TYPES:
        raise ValidationFailed(f"doc_type must be one of: {', '.join(sorted(DOC_TYPES))}")
    meta.setdefault("source", Path(filename).name)
    meta["title"] = parsed.title
    doc_id = doc_id_for(filename, meta)
    meta["doc_id"] = doc_id
    meta["is_sample"] = is_sample

    existing = session.get(KnowledgeDoc, doc_id)
    if existing is not None:
        store.delete_doc(doc_id)  # re-ingest replaces old chunks
    chunks = chunk_document(doc_id, parsed, settings.rag_chunk_chars, settings.rag_chunk_overlap)
    n = store.upsert(chunks)
    record = existing or KnowledgeDoc(id=doc_id, title=parsed.title, doc_type=doc_type, source=str(meta["source"]),
                                      content_hash="", embedder=store.embedder.name)
    record.title, record.doc_type, record.source = parsed.title, doc_type, str(meta["source"])
    record.doc_metadata = {k: v for k, v in meta.items() if isinstance(v, (str, int, float, bool, list))}
    record.chunk_count, record.content_hash = n, content_hash(data)
    record.embedder, record.is_sample = store.embedder.name, is_sample
    session.add(record)
    session.commit()
    return record
