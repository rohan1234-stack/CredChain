import uuid
from datetime import datetime

from pydantic import BaseModel


class NotificationCounts(BaseModel):
    """
    Role-aware pending-action counts, each a real COUNT(...) query against
    existing status columns — never a fabricated number, never persisted
    read/unread state. See app/services/notification_service.py for exactly
    what each count means and why it's honestly "pending my action" rather
    than a generic unread tally.

    This answers "what currently needs my action?" — a DIFFERENT question
    from the Notification center below ("what new events do I have?"). Both
    are real and both stay; this schema/endpoint is unchanged by the
    notification center feature.
    """

    # Student
    pending_company_requests: int | None = None
    # Institution
    pending_certificate_requests: int | None = None
    pending_document_reviews: int | None = None
    # Company/verifier
    unverified_shared_credentials: int | None = None
    new_job_applications: int | None = None


class NotificationResponse(BaseModel):
    """
    One recipient's own notification. Deliberately excludes user_id and
    activity_log_id — internal linkage never meant for direct client
    exposure; title/message are the pre-rendered, safe display text decided
    server-side at creation time (see notification_service.create_notification).
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    title: str
    message: str
    link_entity_type: str | None
    link_entity_id: uuid.UUID | None
    is_read: bool
    read_at: datetime | None
    created_at: datetime
