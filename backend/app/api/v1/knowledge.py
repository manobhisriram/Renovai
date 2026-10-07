from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import current_user, get_container, get_db, rate_limit, require_roles
from app.database.models import KnowledgeDoc
from app.rag.ingest import MAX_DOC_BYTES, ingest_bytes
from app.schemas.api import RagSearch
from app.services.audit import audit
from app.services.container import Container
from app.utils.errors import NotFoundError

router = APIRouter(prefix="/rag", tags=["rag"], dependencies=[Depends(current_user), Depends(rate_limit("api"))])


def doc_view(d: KnowledgeDoc) -> dict[str, Any]:
    return {"id": d.id, "title": d.title, "doc_type": d.doc_type, "source": d.source, "metadata": d.doc_metadata, "chunk_count": d.chunk_count,
            "embedder": d.embedder, "is_sample": d.is_sample, "created_at": d.created_at.isoformat()}


@router.get("/documents")
def list_documents(doc_type: str | None = None, db: Session = Depends(get_db)) -> list[dict]:
    stmt = select(KnowledgeDoc).order_by(KnowledgeDoc.created_at.desc())
    if doc_type:
        stmt = stmt.where(KnowledgeDoc.doc_type == doc_type)
    return [doc_view(d) for d in db.scalars(stmt)]


@router.post("/documents", status_code=201)
def upload_document(file: UploadFile = File(...), doc_type: str = Form("document"), category: str | None = Form(None),
                    room_type: str | None = Form(None), location: str | None = Form(None), budget_range: str | None = Form(None),
                    material_type: str | None = Form(None), db: Session = Depends(get_db), c: Container = Depends(get_container),
                    user=Depends(require_roles("admin"))) -> dict:
    data = file.file.read(MAX_DOC_BYTES + 1)
    meta = {k: v for k, v in {"doc_type": doc_type, "category": category, "room_type": room_type, "location": location,
                              "budget_range": budget_range, "material_type": material_type}.items() if v}
    c.store.ensure_collection()
    doc = ingest_bytes(session=db, store=c.store, settings=c.settings, filename=file.filename or "document.txt", data=data, metadata=meta)
    audit(db, user.email, "rag.document_ingested", detail={"doc_id": doc.id, "type": doc.doc_type, "chunks": doc.chunk_count})
    db.commit()
    return doc_view(doc)


@router.delete("/documents/{doc_id}", status_code=204)
def delete_document(doc_id: str, db: Session = Depends(get_db), c: Container = Depends(get_container), user=Depends(require_roles("admin"))) -> Response:
    d = db.get(KnowledgeDoc, doc_id)
    if d is None:
        raise NotFoundError("Document not found.")
    c.store.delete_doc(doc_id)
    db.delete(d)
    audit(db, user.email, "rag.document_deleted", detail={"doc_id": doc_id})
    db.commit()
    return Response(status_code=204)


@router.post("/search")
def search(body: RagSearch, c: Container = Depends(get_container)) -> dict:
    filters = {k: v for k, v in {"doc_type": body.doc_type, "category": body.category}.items() if v}
    res = c.retriever.retrieve(body.query, filters=filters or None, preferred={"category": body.category}, top_k=body.top_k)
    return {"query": body.query, "latency_ms": res.latency_ms, "degraded": res.degraded, "evidence": [e.to_dict() for e in res.evidence]}


