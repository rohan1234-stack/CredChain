import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Briefcase, MapPin, Timer, Check } from 'lucide-react'
import { getOpenJobsPage } from '../../lib/api'
import { ApiError } from '../../lib/apiClient'
import type { Job } from '../../types'
import { GlassPanel, Badge, EmptyState, SearchInput, FilterPills, Button, Pagination } from '../../components/ui'
import { SkeletonCard } from '../../components/ui/Skeleton'

const PAGE_SIZE = 24

const EMPLOYMENT_LABEL: Record<string, string> = {
  full_time: 'Full-time',
  part_time: 'Part-time',
  internship: 'Internship',
  contract: 'Contract',
}

type EligFilter = 'all' | 'eligible' | 'incomplete'

/**
 * Reproduces Stitch's "career_opportunities" bento job grid (see
 * stitch1/career_opportunities/code.html): header + glass search bar + quick
 * filter pills, then a masonry-style grid of glass job cards (logo tile,
 * title/company, an eligibility badge, a 2-column meta strip, eligibility
 * requirement chips, deadline + apply footer). Stitch's own reference shows
 * a fabricated "98% Match" score and fake company names/salaries on this
 * list screen — this app has no per-job match-percentage computation until
 * a student opens Job Detail's real AI analysis, so the badge here uses the
 * real deterministic `job.eligibility.status` instead, and every other value
 * is a real Job field already returned by getOpenJobsPage().
 */
export function Jobs() {
  const [jobs, setJobs] = useState<Job[]>([])
  const [total, setTotal] = useState(0)
  const [totalPages, setTotalPages] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<EligFilter>('all')
  const [hasSearched, setHasSearched] = useState(false)
  const [page, setPage] = useState(1)

  // Any search change resets to page 1 — otherwise a narrower search could land on a page past
  // the new, smaller result set (same render-time-reset pattern as Institutions.tsx/Companies.tsx).
  const [prevQuery, setPrevQuery] = useState(query)
  if (prevQuery !== query) {
    setPrevQuery(query)
    setPage(1)
  }

  // Backend-driven search (GET /api/jobs?search=...&page=...), debounced so it doesn't fire a
  // request per keystroke. The backend `search` param matches title, description, AND company
  // name — same fields this page has always let a student search by — so this is a pure
  // refactor, not a behavior change. The eligibility pill filter stays client-side: it's not a
  // stable query filter (eligibility is computed per-student per-request), just a view over
  // whatever the current page already returned.
  useEffect(() => {
    const handle = setTimeout(() => {
      setLoading(true)
      setError(null)
      getOpenJobsPage({ search: query.trim() || undefined, page, pageSize: PAGE_SIZE })
        .then((data) => {
          setJobs(data.items)
          setTotal(data.total)
          setTotalPages(data.total_pages)
          setHasSearched(true)
        })
        .catch((err) => setError(err instanceof ApiError ? err.message : 'Unable to load jobs. Please try again.'))
        .finally(() => setLoading(false))
    }, 300)
    return () => clearTimeout(handle)
  }, [query, page])

  const filtered = useMemo(() => {
    if (filter === 'all') return jobs
    return jobs.filter((j) => filter === 'eligible' ? j.eligibility?.status === 'eligible' : j.eligibility?.status === 'incomplete')
  }, [jobs, filter])

  if (loading && jobs.length === 0 && !error) return <div className="space-y-4"><SkeletonCard lines={3} /><SkeletonCard lines={3} /></div>

  return (
    <div>
      <div className="mb-5">
        <h1 className="text-2xl font-bold tracking-tight text-ink font-[family-name:var(--font-display)]">Career Opportunities</h1>
        <p className="mt-1 text-[15px] text-muted">Matched against your real, signed credentials.</p>
      </div>

      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
        <SearchInput placeholder="Search roles or companies…" value={query} onChange={(e) => setQuery(e.target.value)} className="max-w-sm" />
        <FilterPills
          value={filter}
          onChange={setFilter}
          options={[
            { value: 'all', label: 'All' },
            { value: 'eligible', label: 'Eligible' },
            { value: 'incomplete', label: 'Incomplete data' },
          ]}
        />
      </div>

      {error && <div className="mb-5 max-w-2xl rounded-lg bg-bad-bg px-3.5 py-2.5 text-[13px] text-bad">{error}</div>}

      {filtered.length === 0 && hasSearched ? (
        !error && (
          <EmptyState
            icon={Briefcase}
            title="No open jobs"
            description={
              jobs.length === 0
                ? query
                  ? `No open jobs found matching "${query}".`
                  : 'No companies have published a job yet.'
                : 'Try a different search term or filter.'
            }
          />
        )
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {filtered.map((j) => {
            const eligTone = j.eligibility?.status === 'eligible' ? 'good' : j.eligibility?.status === 'incomplete' ? 'warn' : 'bad'
            const eligLabel = j.eligibility?.status === 'eligible' ? 'Eligible' : j.eligibility?.status === 'incomplete' ? 'Incomplete' : 'Not Eligible'
            const deadlinePassed = j.application_deadline != null && new Date(j.application_deadline).getTime() < Date.now()
            return (
              <GlassPanel key={j.id} className="flex flex-col gap-3 p-5 transition-transform duration-300 hover:-translate-y-1">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-3">
                    <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-white/5 bg-canvas-2">
                      <Briefcase className="h-5 w-5 text-muted" strokeWidth={1.75} />
                    </div>
                    <div>
                      <h3 className="text-[15px] font-bold leading-tight text-ink">{j.title}</h3>
                      <p className="text-xs text-muted">{j.company_name}</p>
                    </div>
                  </div>
                  {j.eligibility && (
                    <Badge tone={eligTone} size="sm">
                      {eligLabel}
                    </Badge>
                  )}
                </div>

                <div className="grid grid-cols-2 gap-2 text-[12px]">
                  {j.location && (
                    <span className="flex items-center gap-1 text-body">
                      <MapPin className="h-3.5 w-3.5 text-cyan" /> {j.location}
                    </span>
                  )}
                  <span className="text-body">{EMPLOYMENT_LABEL[j.employment_type]}</span>
                </div>

                {(j.required_degree || j.minimum_cgpa != null || j.graduation_year_requirement) && (
                  <div>
                    <p className="mb-1 text-[10px] font-bold uppercase tracking-wider text-faint">Eligibility Requirements</p>
                    <div className="flex flex-wrap gap-1.5">
                      {j.required_degree && (
                        <span className="rounded-md border border-white/5 bg-canvas-2 px-2 py-1 font-[family-name:var(--font-mono)] text-[11px] text-body">
                          {j.required_degree}
                        </span>
                      )}
                      {j.minimum_cgpa != null && (
                        <span className="flex items-center gap-1 rounded-md border border-good-line bg-good-bg px-2 py-1 font-[family-name:var(--font-mono)] text-[11px] text-good">
                          <Check className="h-3 w-3" /> Min CGPA {j.minimum_cgpa.toFixed(2)}
                        </span>
                      )}
                      {j.graduation_year_requirement && (
                        <span className="rounded-md border border-white/5 bg-canvas-2 px-2 py-1 font-[family-name:var(--font-mono)] text-[11px] text-body">
                          Class of {j.graduation_year_requirement}
                        </span>
                      )}
                    </div>
                  </div>
                )}

                <p className="line-clamp-2 text-[13px] text-body">{j.description}</p>

                <div className="mt-auto flex items-center justify-between border-t border-white/5 pt-3">
                  {j.application_deadline ? (
                    <p className={`flex items-center gap-1 text-[12px] ${deadlinePassed ? 'text-bad' : 'text-muted'}`}>
                      <Timer className="h-3.5 w-3.5" />
                      {deadlinePassed ? 'Closed' : `Closes ${new Date(j.application_deadline).toLocaleDateString()}`}
                    </p>
                  ) : (
                    <span />
                  )}
                  <Link to={`/student/jobs/${j.id}`}>
                    <Button variant="solid" size="sm">
                      View Details
                    </Button>
                  </Link>
                </div>
              </GlassPanel>
            )
          })}
        </div>
      )}

      {!error && <Pagination page={page} totalPages={totalPages} total={total} onPageChange={setPage} />}
    </div>
  )
}
