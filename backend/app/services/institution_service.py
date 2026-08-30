from uuid import UUID

from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import Session

from ..models.institution import Institution
from ..schemas.institution import InstitutionSummaryResponse
from ..schemas.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Page


def list_institutions(
    db: Session,
    *,
    search: str | None = None,
    location: str | None = None,
    country: str | None = None,
    region: str | None = None,
    institution_type: str | None = None,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> tuple[list[Institution], int]:
    """
    Public institution directory listing (also reused, unchanged in shape,
    by the registration/link-institution picker — see routes/institutions.py).

    search matches name/location/city (case-insensitive substring — cheap at
    this dataset size; a dataset large enough to need a real full-text index
    would call for pg_trgm, noted as a follow-up in docs/DIRECTORY.md).
    institution_type is an exact (case-insensitive) match against the
    structured column a real import populates. region is a substring match:
    state/province naming isn't as standardized across sources as country
    names are.

    country matches the structured `country` column when a row has one
    (real imports always populate it); for a row that doesn't — every one of
    Phase 1's manually curated institutions, which predate this column and
    only ever got a combined "City, State, Country" `location` string —
    it falls back to a substring match against `location` instead. Without
    this fallback, filtering by country would silently stop finding any
    Phase 1 institution the moment this column was added, since a plain
    `country = X` filter only matches rows that HAVE a `country` value.

    Returns (page_of_rows, total_matching_count) — never the whole table.

    Ordering: when searching, a name that STARTS WITH the search term ranks
    ahead of one that merely contains it elsewhere (e.g. "Aalto University"
    ranks before a name that only mentions "Aalto" mid-string) — substring
    matches still appear, just after every prefix match. Within each group,
    plain case-insensitive alphabetical, with id as the final deterministic
    tie-breaker. No search term means no ranking to compute — just
    alphabetical.
    """
    page = max(1, page)
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))

    query = db.query(Institution)
    if search:
        needle = f"%{search.strip()}%"
        query = query.filter(or_(Institution.name.ilike(needle), Institution.location.ilike(needle), Institution.city.ilike(needle)))
    if location:
        query = query.filter(Institution.location.ilike(f"%{location.strip()}%"))
    if country:
        needle = country.strip()
        query = query.filter(
            or_(
                Institution.country.ilike(needle),
                and_(Institution.country.is_(None), Institution.location.ilike(f"%{needle}%")),
            )
        )
    if region:
        query = query.filter(Institution.region.ilike(f"%{region.strip()}%"))
    if institution_type:
        query = query.filter(Institution.institution_type.ilike(institution_type.strip()))

    order_columns = []
    if search:
        prefix_pattern = f"{search.strip().lower()}%"
        order_columns.append(case((func.lower(Institution.name).like(prefix_pattern), 0), else_=1))
    order_columns.extend([func.lower(Institution.name), Institution.id])

    total = query.count()
    rows = query.order_by(*order_columns).offset((page - 1) * page_size).limit(page_size).all()
    return rows, total


def get_institution(db: Session, institution_id: UUID) -> Institution | None:
    return db.get(Institution, institution_id)


def to_response(institution: Institution) -> InstitutionSummaryResponse:
    return InstitutionSummaryResponse(
        id=institution.id,
        name=institution.name,
        description=institution.description,
        location=institution.location,
        website=institution.website,
        institution_type=institution.institution_type,
        country=institution.country,
        region=institution.region,
        city=institution.city,
        logo_url=institution.logo_url,
        source=institution.source,
        is_registered=institution.user_id is not None,
        verification_status=institution.verification_status.value if institution.user_id is not None else None,
    )


def to_page_response(rows: list[Institution], *, total: int, page: int, page_size: int) -> Page[InstitutionSummaryResponse]:
    return Page.of([to_response(i) for i in rows], page=page, page_size=page_size, total=total)
