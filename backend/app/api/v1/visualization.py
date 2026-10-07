from __future__ import annotations

import io
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import current_user, get_container, get_db, rate_limit
from app.database.models import GeneratedVisual, ProjectImage
from app.schemas.api import VisualizationRequest
from app.services.audit import audit
from app.services.container import Container
from app.services.projects import get_project, latest_requirements
from app.utils.errors import AppError, NotFoundError
from app.viz.providers import DISCLAIMER, build_prompt, stamp_disclaimer

router = APIRouter(prefix="/projects", tags=["visualization"], dependencies=[Depends(current_user), Depends(rate_limit("api"))])


def _vis(v: GeneratedVisual) -> dict:
    return {"id": v.id, "provider": v.provider, "prompt": v.prompt, "status": v.status, "error": v.error, "source_image_id": v.source_image_id,
            "created_at": v.created_at.isoformat(), "disclaimer": DISCLAIMER}


@router.get("/{project_id}/visualizations")
def list_visuals(project_id: str, db: Session = Depends(get_db), c: Container = Depends(get_container)) -> dict:
    get_project(db, project_id)
    rows = db.scalars(select(GeneratedVisual).where(GeneratedVisual.project_id == project_id).order_by(GeneratedVisual.created_at.desc()))
    return {"enabled": c.viz.name != "none", "provider": c.viz.name, "items": [_vis(v) for v in rows]}


@router.post("/{project_id}/visualizations", status_code=201, dependencies=[Depends(rate_limit("viz", "auth_rate_limit_per_minute"))])
def create_visual(project_id: str, body: VisualizationRequest, db: Session = Depends(get_db), c: Container = Depends(get_container),
                  user=Depends(current_user)) -> dict:
    p = get_project(db, project_id)
    req = latest_requirements(db, project_id) or {}
    prompt = build_prompt(body.prompt, style=req.get("desired_style"), category=p.category, constraints=req.get("constraints") or [])
    source: bytes | None = None
    if body.image_id:
        img = db.get(ProjectImage, body.image_id)
        if img is None or img.project_id != project_id:
            raise NotFoundError("Source image not found.")
        with Image.open(io.BytesIO(c.storage.get(img.storage_key))) as im:
            buf = io.BytesIO()
            im.convert("RGB").save(buf, "PNG")
            source = buf.getvalue()
    vis = GeneratedVisual(project_id=project_id, source_image_id=body.image_id, provider=c.viz.name, prompt=prompt, status="failed")
    db.add(vis)
    db.flush()
    try:
        png = stamp_disclaimer(c.viz.generate(prompt, source))  # raises ServiceNotConfigured / ExternalServiceError
        key = f"projects/{project_id}/viz/{uuid.uuid4().hex}.png"
        c.storage.put(key, png, "image/png")
        vis.storage_key, vis.status = key, "completed"
    except AppError as exc:
        vis.error = exc.message
        audit(db, user.email, "visualization.failed", project_id=project_id, detail={"error": exc.message})
        db.commit()
        raise
    audit(db, user.email, "visualization.created", project_id=project_id)
    db.commit()
    return _vis(vis)


@router.get("/{project_id}/visualizations/{vis_id}/content")
def visual_content(project_id: str, vis_id: str, db: Session = Depends(get_db), c: Container = Depends(get_container)) -> Response:
    v = db.get(GeneratedVisual, vis_id)
    if v is None or v.project_id != project_id or not v.storage_key:
        raise NotFoundError("Visualisation not found.")
    return Response(c.storage.get(v.storage_key), media_type="image/png", headers={"Cache-Control": "private, max-age=300"})
