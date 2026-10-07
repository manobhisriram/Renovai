from __future__ import annotations

from collections.abc import Callable, Iterator

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.security import decode_token
from app.database.models import User
from app.observability.context import user_id_var
from app.services.container import Container
from app.utils.errors import ForbiddenError, RateLimited, UnauthorizedError

bearer = HTTPBearer(auto_error=False)


def get_container(request: Request) -> Container:
    return request.app.state.container


def get_db(container: Container = Depends(get_container)) -> Iterator[Session]:
    session = container.session_factory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def current_user(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(bearer),
                 container: Container = Depends(get_container), db: Session = Depends(get_db)) -> User:
    if creds is None:
        raise UnauthorizedError("Sign in to continue.")
    claims = decode_token(container.settings, creds.credentials)
    user = db.get(User, claims["sub"])
    if user is None or not user.is_active:
        raise UnauthorizedError("This account is not active.")
    user_id_var.set(user.id)
    request.state.user_id = user.id  # read by the access-log middleware (context vars don't cross the threadpool boundary)
    return user


def require_roles(*roles: str) -> Callable[[User], User]:
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise ForbiddenError(f"This action requires one of the roles: {', '.join(roles)}.")
        return user

    return dep


def rate_limit(bucket: str, per_minute_attr: str = "rate_limit_per_minute") -> Callable[[Request], None]:
    def dep(request: Request) -> None:
        c: Container = request.app.state.container
        limit = getattr(c.settings, per_minute_attr)
        ip = request.client.host if request.client else "unknown"
        ok, retry = request.app.state.limiter.check(f"{bucket}:{ip}", limit)
        if not ok:
            raise RateLimited(f"Too many requests. Try again in {retry} seconds.", details={"retry_after": retry})

    return dep
