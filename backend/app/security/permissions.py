# ---------------------------------------------------------------------------
# FastAPI auth dependencies: get_current_user() + role-gated dependencies.
#
# This is the ONE place role authorization is enforced. Every route that
# needs auth depends on get_current_user (or one of the require_* helpers
# below) — never re-implement token parsing in a route.
# ---------------------------------------------------------------------------

import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.enums import UserRole
from ..models.user import User
from .jwt import decode_access_token

# auto_error=False so a missing header raises our own 401 with a consistent
# body/shape, instead of FastAPI's default "Not authenticated" 403.
_bearer_scheme = HTTPBearer(auto_error=False)

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Reads Authorization: Bearer <token>, validates signature + expiry, loads
    the user from Postgres, confirms is_active. Raises 401 for every failure
    mode (missing header, bad signature, expired, unknown user id, inactive
    account) — deliberately without distinguishing *which* failure in the
    response, so a stolen/expired token can't be used to enumerate valid
    user ids.
    """
    if credentials is None:
        raise _UNAUTHORIZED

    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise _UNAUTHORIZED

    raw_subject = payload.get("sub")
    if raw_subject is None:
        raise _UNAUTHORIZED

    try:
        user_id = uuid.UUID(raw_subject)
    except ValueError:
        raise _UNAUTHORIZED

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise _UNAUTHORIZED

    return user


def require_role(*allowed_roles: UserRole):
    """Factory for a dependency that additionally requires the caller's role to be one of allowed_roles (else 403)."""

    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this resource",
            )
        return current_user

    return dependency


require_student = require_role(UserRole.STUDENT)
require_institution = require_role(UserRole.INSTITUTION)
require_verifier = require_role(UserRole.VERIFIER)
require_admin = require_role(UserRole.ADMIN)
