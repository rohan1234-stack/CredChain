from uuid import UUID

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


def _open_job_counts(db: Session, company_ids: list[UUID]) -> dict[UUID, int]:
    """
    One aggregate query for however many company ids are passed, instead of one COUNT query
    per company — the batched replacement for what used to be a per-row _open_job_count call
    in to_page_response's serialization loop (the confirmed N+1 behind /api/companies' latency
    on an unfiltered/wide page). A company with no OPEN jobs simply has no row in the result, so
    callers must treat a missing key as 0 (see to_response's .get(..., 0) below) — never assume
    every id passed in comes back out.
    """
    if not company_ids:
        return {}
    rows = (
        db.query(Job.company_id, func.count(Job.id))
        .filter(Job.company_id.in_(company_ids), Job.status == JobStatus.OPEN)
        .group_by(Job.company_id)
        .all()
    )
    return dict(rows)


def to_response(db: Session, company: Company, *, open_positions_count: int | None = None) -> CompanyProfileResponse:
    """
    open_positions_count: pass the already-looked-up count when serializing a page of many
    companies (see to_page_response, which batches all of them in one _open_job_counts call).
    Left as None for a single-company call (get_my_profile/update_my_profile/get_company in
    routes/companies.py) — that path still needs exactly one lookup, which is not an N+1
    pattern since there's only ever one company to look up there.
    """
    if open_positions_count is None:
        open_positions_count = _open_job_counts(db, [company.id]).get(company.id, 0)
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
        open_positions_count=open_positions_count,
    )


def to_page_response(db: Session, rows: list[Company], *, total: int, page: int, page_size: int) -> Page[CompanyProfileResponse]:
    counts = _open_job_counts(db, [c.id for c in rows])
    items = [to_response(db, c, open_positions_count=counts.get(c.id, 0)) for c in rows]
    return Page.of(items, page=page, page_size=page_size, total=total)


def update_profile(db: Session, company: Company, payload: UpdateCompanyProfileBody) -> Company:
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(company, field, value)
    db.add(company)
    db.commit()
    db.refresh(company)
    return company
