from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from ..models.company import Company
from ..models.enums import JobStatus
from ..models.job import Job
from ..schemas.company import CompanyProfileResponse, UpdateCompanyProfileBody
from ..schemas.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Page


def list_companies(
    db: Session,
    *,
    search: str | None = None,
    industry: str | None = None,
    location: str | None = None,
    country: str | None = None,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> tuple[list[Company], int]:
    """
    Public company directory listing. search matches name/industry/location
    (case-insensitive substring). industry/country are exact (case-insensitive)
    matches; location stays a free-text substring match over the legacy
    combined field (see list_institutions for the same country-vs-location
    rationale). Returns (page_of_rows, total_matching_count) — never the
    whole table.

    Ordering: when searching, a name that STARTS WITH the search term ranks
    ahead of one that merely contains it elsewhere (e.g. "Infosys" ranks
    before "Global Infrastructure Partners" for search "Inf") — substring
    matches still appear, just after every prefix match. Within each group,
    plain case-insensitive alphabetical, with id as the final deterministic
    tie-breaker. No search term means no ranking to compute — just
    alphabetical.
    """
    page = max(1, page)
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))

    query = db.query(Company)
    if search:
        needle = f"%{search.strip()}%"
        query = query.filter(
            or_(Company.name.ilike(needle), Company.industry.ilike(needle), Company.location.ilike(needle))
        )
    if industry:
        query = query.filter(Company.industry.ilike(industry.strip()))
    if location:
        query = query.filter(Company.location.ilike(f"%{location.strip()}%"))
    if country:
        query = query.filter(Company.country.ilike(country.strip()))

    order_columns = []
    if search:
        prefix_pattern = f"{search.strip().lower()}%"
        order_columns.append(case((func.lower(Company.name).like(prefix_pattern), 0), else_=1))
    order_columns.extend([func.lower(Company.name), Company.id])

    total = query.count()
    rows = query.order_by(*order_columns).offset((page - 1) * page_size).limit(page_size).all()
    return rows, total


def _open_job_count(db: Session, company_id) -> int:
    return db.query(func.count(Job.id)).filter(Job.company_id == company_id, Job.status == JobStatus.OPEN).scalar() or 0


def to_response(db: Session, company: Company) -> CompanyProfileResponse:
    return CompanyProfileResponse(
        id=company.id,
        name=company.name,
        industry=company.industry,
        website=company.website,
        description=company.description,
        location=company.location,
        company_size=company.company_size,
        created_at=company.created_at,
        country=company.country,
        region=company.region,
        city=company.city,
        logo_url=company.logo_url,
        source=company.source,
        is_registered=company.user_id is not None,
        verification_status=company.verification_status.value if company.user_id is not None else None,
        open_positions_count=_open_job_count(db, company.id),
    )


def to_page_response(db: Session, rows: list[Company], *, total: int, page: int, page_size: int) -> Page[CompanyProfileResponse]:
    return Page.of([to_response(db, c) for c in rows], page=page, page_size=page_size, total=total)


def update_profile(db: Session, company: Company, payload: UpdateCompanyProfileBody) -> Company:
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(company, field, value)
    db.add(company)
    db.commit()
    db.refresh(company)
    return company
