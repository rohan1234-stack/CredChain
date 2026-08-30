# ---------------------------------------------------------------------------
# Import every model module here so Base.metadata is fully populated before
# Alembic autogenerate (or Base.metadata.create_all) runs. Import order does
# not matter to SQLAlchemy (FK dependency ordering is resolved at DDL-emit
# time), but this order roughly follows the entity dependency chain for
# readability.
# ---------------------------------------------------------------------------

from .activity_log import ActivityLog
from .company import Company
from .credential import Credential
from .credential_document import CredentialDocument
from .credential_request import CredentialRequest
from .institution import Institution
from .institution_certificate_request import InstitutionCertificateRequest
from .job import Job
from .job_application import JobApplication
from .notification import Notification
from .share_grant import ShareGrant, ShareGrantCredential
from .student import Student
from .student_document import StudentDocument
from .user import User
from .verification_event import VerificationEvent

__all__ = [
    "ActivityLog",
    "Company",
    "Credential",
    "CredentialDocument",
    "CredentialRequest",
    "Institution",
    "InstitutionCertificateRequest",
    "Job",
    "JobApplication",
    "Notification",
    "ShareGrant",
    "ShareGrantCredential",
    "Student",
    "StudentDocument",
    "User",
    "VerificationEvent",
]
