import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.enums import UserRole
from ..models.user import User
from ..schemas.notifications import NotificationCounts, NotificationResponse
from ..schemas.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Page
from ..security.permissions import get_current_user
from ..services import notification_service

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get(
    "/me/counts",
    response_model=NotificationCounts,
    summary="Real, role-scoped pending-action counts for the authenticated user — never a hardcoded number",
)
def get_my_notification_counts(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> NotificationCounts:
    if current_user.role == UserRole.STUDENT:
        if current_user.student is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No student profile for this account")
        return notification_service.student_counts(db, current_user.student)
    if current_user.role == UserRole.INSTITUTION:
        if current_user.institution is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No institution profile for this account")
        return notification_service.institution_counts(db, current_user.institution)
    if current_user.company is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No company profile for this account")
    return notification_service.company_counts(db, current_user.company)


# ---------------------------------------------------------------------------
# The notification center itself — "what new events do I have?", a distinct
# question from /me/counts above ("what currently needs my action?"). Every
# route here derives the recipient from current_user only; no route accepts
# a client-supplied user_id, and mark-one/mark-all are scoped to
# current_user.id inside notification_service — cross-user access is
# structurally impossible, not just filtered out after the fact.
# ---------------------------------------------------------------------------


@router.get(
    "/me",
    response_model=Page[NotificationResponse],
    summary="The authenticated user's own notifications, newest first — paginated, never the full history in one response",
)
def list_my_notifications(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Page[NotificationResponse]:
    notifications, total = notification_service.list_notifications_for_user(db, current_user, page=page, page_size=page_size)
    return Page.of([NotificationResponse.model_validate(n) for n in notifications], page=page, page_size=page_size, total=total)


@router.get(
    "/me/unread-count",
    summary="How many of the authenticated user's notifications are unread — cheap, index-backed count for the bell badge",
)
def get_my_unread_notification_count(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> int:
    return notification_service.count_unread_notifications(db, current_user)


@router.post(
    "/me/{notification_id}/read",
    response_model=NotificationResponse,
    summary="Mark one of the authenticated user's own notifications read",
)
def mark_notification_read(
    notification_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> NotificationResponse:
    try:
        notification = notification_service.mark_notification_read(db, current_user, notification_id)
    except notification_service.NotificationNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    except notification_service.NotificationNotOwnedError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This notification does not belong to you")
    return NotificationResponse.model_validate(notification)


@router.post(
    "/me/read-all",
    summary="Mark all of the authenticated user's own unread notifications read — never touches another user's notifications",
)
def mark_all_notifications_read(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    updated = notification_service.mark_all_notifications_read(db, current_user)
    return {"updated": updated}
