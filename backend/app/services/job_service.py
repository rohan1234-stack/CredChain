import uuid

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..models.company import Company
from ..models.enums import JobStatus, VerificationStatus
from ..models.job import Job
from ..models.job_application import JobApplication
from ..models.student import Student
from ..schemas.job import CreateJobBody, EligibilityResult, JobResponse, UpdateJobBody
from ..schemas.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Page
from . import eligibility_service

# Changing any of these after a job has real applications against it would
# silently invalidate what those applicants already saw and were evaluated
# against — e.g. raising minimum_cgpa after a student applied at 8.5 would
# retroactively make their real application look wrong for a requirement
# that didn't exist when they applied. Safer rule (Option A, chosen over
# versioning applications): once ANY application exists for a job, these
# fields become locked; everything else (title, description, location,
# employment_type, deadline, advisory skills/certifications) stays editable
# until the job is closed.
ELIGIBILITY_LOCKED_FIELDS = {"required_degree", "minimum_cgpa", "graduation_year_requirement", "required_documents"}


class JobNotFoundError(Exception):
    pass


class JobNotOwnedError(Exception):
    pass


class JobNotEditableError(Exception):
    pass


class JobEligibilityLockedError(Exception):
    """Raised when an edit would change an eligibility-affecting field on a job that already has real applications."""


class CompanyNotVerifiedError(Exception):
    """Raised by publish_job when the company's account is not VERIFIED. Carries the actual status so the route can give a specific, honest message (pending vs. rejected)."""

    def __init__(self, status: VerificationStatus) -> None:
        self.status = status
        super().__init__(f"company verification status is {status.value}, not verified")


def create_job(db: Session, company: Company, payload: CreateJobBody) -> Job:
    job = Job(
        company_id=company.id,
        title=payload.title,
        description=payload.description,
        location=payload.location,
        employment_type=payload.employment_type,
        required_degree=payload.required_degree,
        minimum_cgpa=payload.minimum_cgpa,
        graduation_year_requirement=payload.graduation_year_requirement,
        required_skills=payload.required_skills,
        required_certifications=payload.required_certifications,
        required_documents=payload.required_documents,
        status=JobStatus.DRAFT,
        application_deadline=payload.application_deadline,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _get_owned_job(db: Session, company: Company, job_id: uuid.UUID) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise JobNotFoundError()
    if job.company_id != company.id:
        raise JobNotOwnedError()
    return job


def update_job(db: Session, company: Company, job_id: uuid.UUID, payload: UpdateJobBody) -> Job:
    job = _get_owned_job(db, company, job_id)
    if job.status == JobStatus.CLOSED:
        raise JobNotEditableError()
    updates = payload.model_dump(exclude_unset=True)

    if updates.keys() & ELIGIBILITY_LOCKED_FIELDS:
        # Only compare fields that would actually CHANGE the stored value —
        # re-submitting the same value the job already has is never blocked.
        changed = {f for f in updates.keys() & ELIGIBILITY_LOCKED_FIELDS if getattr(job, f) != updates[f]}
        if changed:
            has_applications = db.query(JobApplication).filter(JobApplication.job_id == job.id).first() is not None
            if has_applications:
                raise JobEligibilityLockedError()

    for field, value in updates.items():
        setattr(job, field, value)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def publish_job(db: Session, company: Company, job_id: uuid.UUID) -> Job:
    job = _get_owned_job(db, company, job_id)
    if job.status != JobStatus.DRAFT:
        raise JobNotEditableError()
    # Phase A: draft creation/editing is allowed for any registered company (see create_job/
    # update_job, both ungated) — publishing (making a job publicly visible to students) is the
    # one action that requires a VERIFIED company.
    if company.verification_status != VerificationStatus.VERIFIED:
        raise CompanyNotVerifiedError(company.verification_status)
    job.status = JobStatus.OPEN
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def close_job(db: Session, company: Company, job_id: uuid.UUID) -> Job:
    job = _get_owned_job(db, company, job_id)
    if job.status == JobStatus.CLOSED:
        raise JobNotEditableError()
    job.status = JobStatus.CLOSED
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def list_jobs_for_company(db: Session, company: Company) -> list[Job]:
    return db.query(Job).filter(Job.company_id == company.id).order_by(Job.created_at.desc()).all()


def list_open_jobs(
    db: Session,
    *,
    search: str | None = None,
    company_id: uuid.UUID | None = None,
    location: str | None = None,
    degree: str | None = None,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> tuple[list[Job], int]:
    """
    search matches title/description/company name (the student Jobs page has always let a
    student search by company name too — the backend filter has to cover that or switching
    the frontend to it would be a regression, not a pure refactor). degree is a substring
    match against required_degree (same free-text matching the eligibility check itself uses
    — no separate degree vocabulary).

    Phase A: paginated the same way institutions/companies already are (see
    institution_service.list_institutions) — filters apply before pagination, and `total`
    reflects the filtered count, never the whole open-jobs table. Returns (page_of_rows,
    total_matching_count).
    """
    page = max(1, page)
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))

    query = db.query(Job).filter(Job.status == JobStatus.OPEN)
    if search:
        needle = f"%{search.strip()}%"
        query = query.join(Company, Job.company_id == Company.id).filter(
            or_(Job.title.ilike(needle), Job.description.ilike(needle), Company.name.ilike(needle))
        )
    if company_id is not None:
        query = query.filter(Job.company_id == company_id)
    if location:
        query = query.filter(Job.location.ilike(f"%{location.strip()}%"))
    if degree:
        query = query.filter(Job.required_degree.ilike(f"%{degree.strip()}%"))

    total = query.count()
    rows = query.order_by(Job.created_at.desc(), Job.id).offset((page - 1) * page_size).limit(page_size).all()
    return rows, total


def get_open_job_or_applied(db: Session, job_id: uuid.UUID, student: Student | None) -> Job:
    """A student may view an OPEN job, or any job (even closed) they've already applied to — never a DRAFT job belonging to someone else."""
    from ..models.job_application import JobApplication

    job = db.get(Job, job_id)
    if job is None:
        raise JobNotFoundError()
    if job.status == JobStatus.OPEN:
        return job
    if student is not None:
        has_applied = (
            db.query(JobApplication).filter(JobApplication.job_id == job.id, JobApplication.student_id == student.id).first()
            is not None
        )
        if has_applied:
            return job
    raise JobNotFoundError()


def to_response(job: Job, *, student: Student | None = None, db: Session | None = None) -> JobResponse:
    eligibility = None
    if student is not None and db is not None:
        result = eligibility_service.evaluate(db, job, student)
        eligibility = EligibilityResult(**result)

    return JobResponse(
        id=job.id,
        company_id=job.company_id,
        company_name=job.company.name,
        title=job.title,
        description=job.description,
        location=job.location,
        employment_type=job.employment_type,
        required_degree=job.required_degree,
        minimum_cgpa=float(job.minimum_cgpa) if job.minimum_cgpa is not None else None,
        graduation_year_requirement=job.graduation_year_requirement,
        required_skills=job.required_skills,
        required_certifications=job.required_certifications,
        required_documents=job.required_documents,
        status=job.status,
        application_deadline=job.application_deadline,
        created_at=job.created_at,
        eligibility=eligibility,
    )


def to_page_response(
    jobs: list[Job], *, student: Student | None, db: Session, total: int, page: int, page_size: int
) -> Page[JobResponse]:
    return Page.of([to_response(j, student=student, db=db) for j in jobs], page=page, page_size=page_size, total=total)
