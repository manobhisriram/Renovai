from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.deps import current_user, get_container, get_db, rate_limit
from app.database.models import AuditEvent, Feedback, Project, ProjectImage
from app.schemas.api import FeedbackIn, ProjectCreate, RequirementsPatch
from app.services.audit import audit
from app.services.container import Container
from app.services.projects import get_or_create_lead, get_project, latest_requirements, save_requirements
from app.services.views import image_view, project_view
from app.utils.errors import ValidationFailed
from app.vision.images import new_storage_key, process_upload, safe_display_name

router = APIRouter(prefix="/projects", tags=["projects"], dependencies=[Depends(current_user), Depends(rate_limit("api"))])


@router.post("", status_code=201)
def create_project(body: ProjectCreate, db: Session = Depends(get_db), user=Depends(current_user)) -> dict:
    lead, _ = get_or_create_lead(db, name=body.lead.name, email=body.lead.email, phone=body.lead.phone)
    p = Project(lead_id=lead.id, title=body.title.strip(), request_text=body.request_text, property_type=body.property_type,
                location=body.location, area_sqm=body.area_sqm, created_by=user.id, status="draft")
    db.add(p)
    db.flush()
    audit(db, user.email, "project.created", project_id=p.id)
    db.commit()
    return project_view(db, p, detail=True)


@router.get("")
def list_projects(status: str | None = None, q: str | None = None, limit: int = 100, db: Session = Depends(get_db)) -> list[dict]:
    stmt = select(Project).order_by(Project.updated_at.desc()).limit(min(limit, 200))
    if status:
        stmt = stmt.where(Project.status == status)
    if q:
        stmt = stmt.where(Project.title.ilike(f"%{q[:80]}%"))
    return [project_view(db, p) for p in db.scalars(stmt)]


@router.get("/{project_id}")
def read_project(project_id: str, db: Session = Depends(get_db)) -> dict:
    return project_view(db, get_project(db, project_id), detail=True)


@router.get("/{project_id}/requirements")
def read_requirements(project_id: str, db: Session = Depends(get_db)) -> dict:
    get_project(db, project_id)
    return {"requirements": latest_requirements(db, project_id)}


@router.patch("/{project_id}/requirements")
def patch_requirements(project_id: str, body: RequirementsPatch, db: Session = Depends(get_db), user=Depends(current_user)) -> dict:
    p = get_project(db, project_id)
    data = latest_requirements(db, project_id) or {"missing_information": [], "confidence": 0.5, "provenance": {}}
    prov = dict(data.get("provenance") or {})
    updates = body.model_dump(exclude_none=True)
    if "budget_amount" in updates:
        data["budget"] = {"amount": updates.pop("budget_amount"), "currency": "INR"}
        prov["budget"] = "user_provided"
    for k, v in updates.items():
        data[k] = v
        prov[k] = "user_provided"
    if "area_sqm" in updates:
        p.area_sqm = updates["area_sqm"]
    if "location" in updates:
        p.location = updates["location"]
    data["provenance"] = prov
    save_requirements(db, project_id, data, "user_edit")
    audit(db, user.email, "requirements.edited", project_id=project_id, detail={"fields": list(body.model_dump(exclude_none=True))})
    db.commit()
    return {"requirements": data}


# ----------------------------------------------------------------------------- images
@router.post("/{project_id}/images", status_code=201, dependencies=[Depends(rate_limit("upload"))])
def upload_images(project_id: str, files: list[UploadFile] = File(...), db: Session = Depends(get_db),
                  c: Container = Depends(get_container), user=Depends(current_user)) -> list[dict]:
    get_project(db, project_id)
    existing = int(db.scalar(select(func.count(ProjectImage.id)).where(ProjectImage.project_id == project_id)) or 0)
    if existing + len(files) > c.settings.max_images_per_project:
        raise ValidationFailed(f"A project can have at most {c.settings.max_images_per_project} photos.")
    out = []
    for f in files:
        data = f.file.read(c.settings.max_upload_bytes + 1)  # bounded read: never loads an unbounded body
        img = process_upload(data, c.settings)
        key = new_storage_key(project_id, img.ext)
        row = ProjectImage(project_id=project_id, storage_key=key, original_filename=safe_display_name(f.filename),
                           content_type=img.content_type, size_bytes=len(img.data), sha256=img.sha256, width=img.width, height=img.height)
        db.add(row)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise ValidationFailed(f"'{row.original_filename}' was already uploaded to this project.") from None
        c.storage.put(key, img.data, img.content_type)
        out.append(image_view(row))
    audit(db, user.email, "images.uploaded", project_id=project_id, detail={"count": len(out)})
    db.commit()
    return out


@router.get("/{project_id}/images")
def list_images(project_id: str, db: Session = Depends(get_db)) -> list[dict]:
    get_project(db, project_id)
    return [image_view(i) for i in db.scalars(select(ProjectImage).where(ProjectImage.project_id == project_id).order_by(ProjectImage.created_at))]


@router.get("/{project_id}/images/{image_id}/content")
def image_content(project_id: str, image_id: str, db: Session = Depends(get_db), c: Container = Depends(get_container)) -> Response:
    from app.utils.errors import NotFoundError

    img = db.get(ProjectImage, image_id)
    if img is None or img.project_id != project_id:
        raise NotFoundError("Image not found.")
    return Response(c.storage.get(img.storage_key), media_type=img.content_type, headers={"Cache-Control": "private, max-age=300",
                                                                                           "Content-Disposition": "inline"})


@router.delete("/{project_id}/images/{image_id}", status_code=204)
def delete_image(project_id: str, image_id: str, db: Session = Depends(get_db), c: Container = Depends(get_container),
                 user=Depends(current_user)) -> Response:
    from app.database.models import ImageAnalysis
    from app.utils.errors import NotFoundError

    img = db.get(ProjectImage, image_id)
    if img is None or img.project_id != project_id:
        raise NotFoundError("Image not found.")
    for a in db.scalars(select(ImageAnalysis).where(ImageAnalysis.image_id == image_id)):
        db.delete(a)
    key = img.storage_key
    db.delete(img)
    audit(db, user.email, "image.deleted", project_id=project_id)
    db.commit()
    c.storage.delete(key)
    return Response(status_code=204)


@router.get("/{project_id}/vision")
def read_vision(project_id: str, db: Session = Depends(get_db)) -> dict:
    from app.database.models import ImageAnalysis
    from app.vision.analyzer import merge_room_facts

    get_project(db, project_id)
    rows = list(db.scalars(select(ImageAnalysis).where(ImageAnalysis.project_id == project_id).order_by(ImageAnalysis.created_at)))
    items = [{"image_id": r.image_id, "model": r.model, "analysis": r.result, "cv": r.cv} for r in rows]
    return {"items": items, "summary": merge_room_facts([r.result for r in rows])}


# ----------------------------------------------------------------------------- feedback & audit
@router.post("/{project_id}/feedback", status_code=201)
def add_feedback(project_id: str, body: FeedbackIn, db: Session = Depends(get_db)) -> dict:
    get_project(db, project_id)
    db.add(Feedback(project_id=project_id, step=body.step, rating=body.rating, comment=body.comment))
    db.commit()
    return {"ok": True}


@router.get("/{project_id}/audit")
def project_audit(project_id: str, db: Session = Depends(get_db)) -> list[dict]:
    get_project(db, project_id)
    rows = db.scalars(select(AuditEvent).where(AuditEvent.project_id == project_id).order_by(AuditEvent.created_at.desc()).limit(200))
    return [{"id": e.id, "actor": e.actor, "action": e.action, "detail": e.detail, "request_id": e.request_id, "created_at": e.created_at.isoformat()} for e in rows]


