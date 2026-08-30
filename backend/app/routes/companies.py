import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.company import Company
from ..models.user import User
from ..schemas.company import CompanyProfileResponse, UpdateCompanyProfileBody
from ..schemas.job import CreateJobBody, JobResponse, UpdateJobBody
from ..schemas.job_application import CompanyApplicationResponse, UpdateApplicationStatusBody
from ..schemas.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Page
from ..security.permissions import require_verifier
from ..services import company_service, job_application_service, job_service

router = APIRouter(prefix="/api/companies", tags=["companies"])


def _company_of(current_user: User) -> Company:
    if current_user.company is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No company profile for this account")
    return current_user.company


@router.get(
    "",
    response_model=Page[CompanyProfileResponse],
    summary=(
        "Paginated, searchable company directory — public, used by students browsing genuine company "
        "profiles (never a source of fabricated company data). Scales to a globally-imported dataset "
        "(see scripts/import_companies.py) — never returns the whole table."
    ),
)
def list_companies(
    search: str | None = Query(default=None, description="Matches company name, industry, or location"),
    industry: str | None = Query(default=None),
    location: str | None = Query(default=None),
    country: str | None = Query(default=None, description="Exact match, e.g. 'India'"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
) -> Page[CompanyProfileResponse]:
    companies, total = company_service.list_companies(
        db, search=search, industry=industry, location=location, country=country, page=page, page_size=page_size
    )
    return company_service.to_page_response(db, companies, total=total, page=page, page_size=page_size)


@router.get("/me", response_model=CompanyProfileResponse, summary="The authenticated company's own profile")
def get_my_profile(current_user: User = Depends(require_verifier), db: Session = Depends(get_db)) -> CompanyProfileResponse:
    if current_user.company is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No company profile for this account")
    return company_service.to_response(db, current_user.company)


@router.patch("/me", response_model=CompanyProfileResponse, summary="Update the authenticated company's own profile — never another company's")
def update_my_profile(
    payload: UpdateCompanyProfileBody,
    current_user: User = Depends(require_verifier),
    db: Session = Depends(get_db),
) -> CompanyProfileResponse:
    if current_user.company is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No company profile for this account")
    updated = company_service.update_profile(db, current_user.company, payload)
    return company_service.to_response(db, updated)


@router.post("/me/jobs", response_model=JobResponse, status_code=status.HTTP_201_CREATED, summary="Create a new job posting — starts as DRAFT, not visible to students until published")
def create_job(payload: CreateJobBody, current_user: User = Depends(require_verifier), db: Session = Depends(get_db)) -> JobResponse:
    company = _company_of(current_user)
    job = job_service.create_job(db, company, payload)
    return job_service.to_response(job)


@router.get("/me/jobs", response_model=list[JobResponse], summary="List the authenticated company's own jobs (any status)")
def list_my_jobs(current_user: User = Depends(require_verifier), db: Session = Depends(get_db)) -> list[JobResponse]:
    company = _company_of(current_user)
    return [job_service.to_response(j) for j in job_service.list_jobs_for_company(db, company)]


@router.patch("/me/jobs/{job_id}", response_model=JobResponse, summary="Edit a job — only while DRAFT or OPEN, never after it's CLOSED")
def update_job(
    job_id: uuid.UUID, payload: UpdateJobBody, current_user: User = Depends(require_verifier), db: Session = Depends(get_db)
) -> JobResponse:
    company = _company_of(current_user)
    try:
        job = job_service.update_job(db, company, job_id, payload)
    except job_service.JobNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    except job_service.JobNotOwnedError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This job does not belong to your company")
    except job_service.JobNotEditableError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A closed job cannot be edited")
    except job_service.JobEligibilityLockedError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This job already has applications — degree, CGPA, graduation year, and required documents can no longer be changed",
        )
    return job_service.to_response(job)


@router.post("/me/jobs/{job_id}/publish", response_model=JobResponse, summary="Publish a DRAFT job — makes it visible to students")
def publish_job(job_id: uuid.UUID, current_user: User = Depends(require_verifier), db: Session = Depends(get_db)) -> JobResponse:
    company = _company_of(current_user)
    try:
        job = job_service.publish_job(db, company, job_id)
    except job_service.JobNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    except job_service.JobNotOwnedError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This job does not belong to your company")
    except job_service.JobNotEditableError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only a draft job can be published")
    except job_service.CompanyNotVerifiedError as exc:
        detail = (
            "Your company's verification was rejected. Jobs cannot be published."
            if exc.status.value == "rejected"
            else "Your company account is pending verification. Jobs cannot be published until an administrator approves it."
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
    return job_service.to_response(job)


@router.post("/me/jobs/{job_id}/close", response_model=JobResponse, summary="Close a job — no longer visible to new applicants")
def close_job(job_id: uuid.UUID, current_user: User = Depends(require_verifier), db: Session = Depends(get_db)) -> JobResponse:
    company = _company_of(current_user)
    try:
        job = job_service.close_job(db, company, job_id)
    except job_service.JobNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    except job_service.JobNotOwnedError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This job does not belong to your company")
    except job_service.JobNotEditableError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This job is already closed")
    return job_service.to_response(job)


@router.get(
    "/me/applications",
    response_model=list[CompanyApplicationResponse],
    summary="List applications to the authenticated company's OWN jobs only — never another company's applicants, never a browse-all-students view",
)
def list_my_applications(current_user: User = Depends(require_verifier), db: Session = Depends(get_db)) -> list[CompanyApplicationResponse]:
    company = _company_of(current_user)
    applications = job_application_service.list_for_company(db, company.id)
    return [job_application_service.to_company_response(db, a) for a in applications]


@router.post(
    "/me/applications/{application_id}/status",
    response_model=CompanyApplicationResponse,
    summary="Company's hiring decision — whitelisted transitions only, company-only, never touched by AI",
)
def update_application_status(
    application_id: uuid.UUID,
    payload: UpdateApplicationStatusBody,
    current_user: User = Depends(require_verifier),
    db: Session = Depends(get_db),
) -> CompanyApplicationResponse:
    company = _company_of(current_user)
    try:
        application = job_application_service.update_status(
            db, company.id, application_id, payload.status, reason=payload.reason
        )
    except job_application_service.ApplicationNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    except job_application_service.ApplicationNotOwnedError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This application does not belong to your company")
    except job_application_service.InvalidStatusTransitionError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That status transition is not allowed")
    except job_application_service.RejectionReasonRequiredError:
        raise HTTPException(status_code=422, detail="A reason is required when rejecting an application")
    return job_application_service.to_company_response(db, application)


@router.get("/{company_id}", response_model=CompanyProfileResponse, summary="View one real company's public profile")
def get_company(company_id: uuid.UUID, db: Session = Depends(get_db)) -> CompanyProfileResponse:
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    return company_service.to_response(db, company)
