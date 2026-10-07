from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import current_user, get_container, get_db, rate_limit, require_roles
from app.auth.security import create_token, hash_password, verify_password
from app.database.models import User
from app.schemas.api import LoginRequest, TokenResponse, UserCreate
from app.services.audit import audit
from app.services.container import Container
from app.utils.errors import ConflictError, ForbiddenError, UnauthorizedError

router = APIRouter(prefix="/auth", tags=["authentication"])

_DUMMY_HASH = hash_password("not-a-real-password")


def user_view(u: User) -> dict:
    return {"id": u.id, "email": u.email, "full_name": u.full_name, "role": u.role, "is_active": u.is_active}


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(rate_limit("auth", "auth_rate_limit_per_minute"))])
def login(body: LoginRequest, db: Session = Depends(get_db), c: Container = Depends(get_container)) -> dict:
    user = db.scalars(select(User).where(User.email == body.email.strip().lower())).first()
    ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)  # constant-ish time for unknown users
    if not user or not ok or not user.is_active:
        audit(db, "anonymous", "auth.login_failed", detail={"email_hash_prefix": body.email[:2] + "***"})
        db.commit()
        raise UnauthorizedError("Email or password is incorrect.")
    audit(db, user.email, "auth.login")
    db.commit()
    return {"access_token": create_token(c.settings, user_id=user.id, role=user.role), "token_type": "bearer", "user": user_view(user)}


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict:
    return user_view(user)


# Open registration only when enabled, or to create the very first (admin) account.
@router.post("/register", status_code=201, dependencies=[Depends(rate_limit("auth", "auth_rate_limit_per_minute"))])
def register(body: UserCreate, db: Session = Depends(get_db), c: Container = Depends(get_container)) -> dict:
    first_user = db.scalars(select(User).limit(1)).first() is None
    if not (first_user or c.settings.allow_self_registration):
        raise ForbiddenError("Registration is closed. Ask an administrator to create your account.")
    if db.scalars(select(User).where(User.email == body.email.lower())).first():
        raise ConflictError("An account with this email already exists.")
    role = "admin" if first_user else "sales"  # self-registration can never choose a role
    user = User(email=body.email.lower(), full_name=body.full_name, password_hash=hash_password(body.password), role=role)
    db.add(user)
    audit(db, body.email, "auth.registered", detail={"role": role})
    db.commit()
    return user_view(user)


@router.post("/admin/users", status_code=201)
def admin_create_user(body: UserCreate, db: Session = Depends(get_db), admin: User = Depends(require_roles("admin"))) -> dict:
    if db.scalars(select(User).where(User.email == body.email.lower())).first():
        raise ConflictError("An account with this email already exists.")
    user = User(email=body.email.lower(), full_name=body.full_name, password_hash=hash_password(body.password), role=body.role)
    db.add(user)
    audit(db, admin.email, "user.created", detail={"email_domain": body.email.split("@")[-1], "role": body.role})
    db.commit()
    return user_view(user)


@router.get("/admin/users")
def list_users(db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))) -> list[dict]:
    return [user_view(u) for u in db.scalars(select(User).order_by(User.created_at))]
