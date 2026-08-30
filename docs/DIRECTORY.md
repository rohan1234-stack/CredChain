# Institution & Company Directory — Architecture

Phase 2 scales CredChain's student-facing Institution/Company/Job discovery
(Phase 1) from a ~56/58-record curated demo dataset into an architecture
that can hold a globally-imported dataset of thousands to tens of thousands
of real records, while keeping every existing flow (auth, credentials,
sharing, eligibility, applications) completely unchanged.

## Directory record vs. registered CredChain account

This distinction is the foundation of everything else here.

- **Directory record** — a row in `institutions` or `companies` with
  `user_id = NULL`. It exists so a student can discover and read about a
  real institution/company (name, location, official website, ...). It has
  no CredChain login, cannot issue credentials, cannot post jobs, and
  cannot receive applications.
- **Registered CredChain account** — a row with `user_id` set, created the
  normal way (that institution/company actually signed up). It behaves
  exactly as it always has.

Both live in the *same* tables and the *same* public list/detail endpoints
— a student sees one directory, and every card/profile explicitly shows
which kind it's looking at (`is_registered`, computed fresh from `user_id`
on every response, never a stored/cacheable claim). "Discoverable" is never
presented as "CredChain partner."

## Schema

Both `institutions` and `companies` gained (migration
`g7a8b9c0d1e2_global_directory_fields`, purely additive):

| column | purpose |
|---|---|
| `country`, `region`, `city` | structured location, indexed on `country` for real equality-filter performance |
| `logo_url` | optional, only ever a source-provided URL |
| `source` | e.g. `manual_curated`, `hipolabs_world_universities`, `wikidata`, or `NULL` for a directly-registered account |
| `source_id` | that source's own stable id for the record (e.g. a Wikidata QID) — the idempotency key an importer looks up before create/update/skip |

`institutions.user_id` / `companies.user_id` were made nullable in Phase 1
for the same reason and are unchanged here.

The existing free-text `location`, `description`, `website`,
`institution_type`/`industry` columns are untouched — Phase 1's manually
curated rows keep working exactly as before, with `country`/`region`/`city`/
`source`/`source_id` simply `NULL` on them until/unless re-imported.

## Data sources

| | Institutions | Companies |
|---|---|---|
| Source | [Hipolabs "world universities"](http://universities.hipolabs.com) | [Wikidata](https://www.wikidata.org) (public SPARQL endpoint) |
| License | Public dataset (derived from the MIT-licensed `Hipo/university-domains-list` project) | CC0 |
| Coverage confirmed live | 10,257 institutions, 201 countries | Real company data confirmed for every configured country (see `scripts/import_companies.py`'s `COUNTRIES` list — 46 major economies, India-first) |
| Fields obtained | name, country, state/province (often absent), official website(s) | name, country, industry, official website |
| Known gaps | no city, no institution type/category, no description | no region/city, industry is Wikidata's own free-text label (not a fixed vocabulary), a small minority of `P856` (website) values on Wikidata can be wrong or stale — see the caveat at the top of `import_companies.py` |

Neither script fabricates a field it can't source: no company gets an
invented description; no institution gets a guessed city. A field the
source doesn't provide is left `NULL` and rendered as "not available" in
the UI, never as fabricated text.

The frontend **never** calls either external source directly — only the
backend's own `/api/institutions` and `/api/companies` endpoints, which
read from Postgres. The import scripts are the only thing that ever talks
to Hipolabs/Wikidata, and only when a maintainer runs them.

### Why not "the whole world" in one shot

Hipolabs' institution dataset genuinely covers ~10,000+ institutions in one
clean JSON endpoint, so `import_institutions.py` can import essentially the
whole thing in one run. There is no equivalent single clean "every company
in the world" dataset that's both free and structured — Wikidata has real
company data, but a global, unconstrained SPARQL query over "every business
entity" times out on Wikidata's shared public endpoint (verified while
building this). `import_companies.py` therefore queries **per configured
country**, each a bounded, provably-completing query, and the country list
is deliberately extensible — running the script again with a longer
`COUNTRIES` list (or a higher `--limit-per-country`) grows the dataset
further without any code change.

## Importing

Both scripts are plain backend commands — never a public API endpoint, per
the "controlled admin operation, not a student-facing action" requirement.

```bash
cd backend
venv\Scripts\Activate.ps1   # or the equivalent on your platform

# Institutions — Hipolabs, no API key needed
python -m scripts.import_institutions                    # every country (~10,000+ records, one HTTP call)
python -m scripts.import_institutions --country India     # one country only
python -m scripts.import_institutions --limit 500          # cap total records fetched (testing)
python -m scripts.import_institutions --dry-run             # fetch + normalize + report; NO database connection, NO writes

# Companies — Wikidata, no API key needed
python -m scripts.import_companies                        # every configured country (~5–10s per country, sequential)
python -m scripts.import_companies --country India          # one country only
python -m scripts.import_companies --limit-per-country 50    # cap records per country (testing)
python -m scripts.import_companies --dry-run                  # fetch + normalize + report; NO database connection, NO writes
```

Both print a final summary: `created=N updated=N skipped_unchanged=N
skipped_duplicate=N skipped_invalid=N`, plus up to 10 example lines for the
duplicate/invalid buckets so a maintainer can spot-check them.

**Never run these as part of a normal app/server startup** (not in
`app/main.py`, not in a Render build/start command) — they're one-off (or
occasionally-rerun) maintenance operations, exactly like
`alembic upgrade head` itself.

## Duplicate handling

1. **Same-source idempotency** — every candidate record's `source_id` (a
   Wikidata QID, or a Hipolabs domain / name+country fallback when no
   domain exists) is looked up against existing rows from *that same
   source* first. A rerun **updates** changed fields (website, region,
   country) on a row it created before, and leaves an unchanged one alone.
   It never creates a second row for something it already imported.
2. **Cross-source duplicate detection** — a candidate that doesn't match by
   source_id is then checked against **every** existing institution/company
   regardless of source (including Phase 1's manually curated rows), by a
   conservative normalized name + country match (lowercase, trimmed,
   whitespace-collapsed — deliberately *not* stripping meaningful words
   like "Institute"/"University", which could turn two different real
   institutions into a false match). A match is **skipped and reported**,
   never silently merged into the existing row and never inserted as a
   duplicate — per the explicit "never merge blindly" requirement.

Both indexes (`build_source_index`, `build_name_country_index` in
`app/services/directory_import_service.py`) are built with **one query
each** at the start of a run and kept in memory for the rest of it — an
O(n) lookup per candidate against a 10,000+ row table, not an O(n²) scan.

## Search, filtering, pagination

`GET /api/institutions` and `GET /api/companies` are always paginated
(`page`, `page_size`, default 24, max 100 — see
`app/schemas/pagination.py`'s `Page[T]`), and return
`{ items, page, page_size, total, total_pages }`. Every filter is a real
SQL `WHERE` clause (`ilike` for free-text search/region/location,
case-insensitive exact match for `country`/`institution_type`/`industry`)
— nothing is fetched in bulk and filtered in React. Results are ordered
deterministically (`name, id`) so pagination doesn't skip/repeat rows
between requests.

**Backward compatibility**: the registration institution-picker and the
direct-share company-picker predate pagination and just want "the list" —
`getInstitutions()`/`getRealCompanies()` in `src/lib/api.ts` still return a
plain array (internally requesting a generous page size and unwrapping
`.items`), so neither of those components needed to change. The new
`getInstitutionsPage()`/`getCompaniesPage()` return the full envelope for
the directory pages' real pagination controls.

**Known scaling limit**: search uses `ILIKE '%term%'`, which can't use a
standard B-tree index (only the exact-match filters like `country` can). At
tens of thousands of rows this is still fast enough for a project of this
size; a genuinely large-scale deployment would add a `pg_trgm` trigram
index for name search (not added here — a new Postgres extension may not
be permitted on every managed-Postgres tier, e.g. some Render plans).

## Credential sharing stays untouched

Nothing in this phase modified `eligibility_service.py`,
`job_application_service.py`, `sharing_service.py`, or any credential
route. Browsing the directory — institution or company, directory-only or
registered — never exposes a credential. The only path that ever creates a
`CredentialRequest`/`ShareGrant` is the existing, unmodified apply flow
(`JobDetail.tsx` → `POST /students/me/applications`), which still requires
the student to explicitly select which credentials to share before
submitting.

## What a student sees

- **Institutions** (`/student/institutions`) — search, country filter,
  region filter, pagination, real result count, loading/empty/error states.
  Each card shows a "Registered" badge only when true.
- **Institution profile** (`/student/institutions/:id`) — same distinction
  as a banner ("Directory Listing" vs "Registered CredChain Institution"),
  About section, "Visit Official Website ↗" (`target="_blank"
  rel="noopener noreferrer"`, only ever the stored URL — never constructed).
- **Companies** (`/student/companies`) — search, country filter, industry
  filter, pagination, open-position count per card.
- **Company profile** (`/student/companies/:id`) — same "External Company"
  vs "Registered CredChain Employer" distinction, About section, real open
  jobs (only ever real `Job` rows — a directory-only company can never have
  one, since posting a job requires a real logged-in account).
- **Jobs** — unchanged from Phase 1; already supports search/company/
  location/degree filtering and the real deterministic eligibility result.
