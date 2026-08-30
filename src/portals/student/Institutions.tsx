import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Landmark, MapPin, Globe, ArrowRight, GraduationCap, ShieldCheck } from 'lucide-react'
import { getInstitutionsPage } from '../../lib/api'
import { ApiError } from '../../lib/apiClient'
import type { InstitutionSummary } from '../../types'
import { PageHeader, SearchInput, GlassPanel, EmptyState, ErrorState, Badge, Pagination } from '../../components/ui'
import { SkeletonCard } from '../../components/ui/Skeleton'
import { COUNTRIES } from '../../lib/countries'

const PAGE_SIZE = 24

/**
 * Student Institution Directory — mirrors the bento glass-card grid already
 * established for the Company directory (see Companies.tsx). Fully
 * backend-paginated/searched (GET /api/institutions?search=&country=&...)
 * so this scales to a globally-imported dataset (tens of thousands of
 * rows) without ever fetching more than one page's worth into the browser.
 */
export function Institutions() {
  const [result, setResult] = useState<{ items: InstitutionSummary[]; total: number; totalPages: number } | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [country, setCountry] = useState('')
  const [region, setRegion] = useState('')
  const [page, setPage] = useState(1)
  const [retryToken, setRetryToken] = useState(0)

  // Any filter change resets to page 1 — otherwise a narrower search could land on a page past
  // the new, smaller result set. Adjusted during render (React's documented pattern for
  // "reset state when a dependency changes") rather than a separate effect, so it takes effect
  // in the same render instead of triggering an extra one.
  const [prevFilters, setPrevFilters] = useState({ query, country, region })
  if (prevFilters.query !== query || prevFilters.country !== country || prevFilters.region !== region) {
    setPrevFilters({ query, country, region })
    setPage(1)
  }

  useEffect(() => {
    const handle = setTimeout(() => {
      setLoading(true)
      setError(null)
      getInstitutionsPage({
        search: query.trim() || undefined,
        country: country || undefined,
        region: region.trim() || undefined,
        page,
        pageSize: PAGE_SIZE,
      })
        .then((data) => setResult({ items: data.items, total: data.total, totalPages: data.total_pages }))
        .catch((err) => setError(err instanceof ApiError ? err.message : 'Could not load institutions.'))
        .finally(() => setLoading(false))
    }, 300)
    return () => clearTimeout(handle)
  }, [query, country, region, page, retryToken])

  return (
    <div>
      <PageHeader
        title="Institutions"
        eyebrow="Academic Discovery"
        icon={Landmark}
        description="Discover universities and academic institutions from around the world."
      />

      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center">
        <SearchInput placeholder="Search institutions…" value={query} onChange={(e) => setQuery(e.target.value)} className="max-w-xs" />
        <select
          value={country}
          onChange={(e) => setCountry(e.target.value)}
          className="rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-primary"
        >
          <option value="">All countries</option>
          {COUNTRIES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <input
          type="text"
          placeholder="State / region…"
          value={region}
          onChange={(e) => setRegion(e.target.value)}
          className="w-40 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink placeholder:text-faint outline-none focus:border-primary"
        />
      </div>

      {error ? (
        <ErrorState description={error} onRetry={() => setRetryToken((t) => t + 1)} />
      ) : loading && !result ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <SkeletonCard lines={3} />
          <SkeletonCard lines={3} />
        </div>
      ) : result && result.items.length === 0 ? (
        <EmptyState
          icon={Landmark}
          title="No institutions found"
          description={query || country || region ? 'No institutions match these filters.' : 'No institutions are in the directory yet.'}
        />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {result?.items.map((inst) => (
              <GlassPanel key={inst.id} className="flex flex-col gap-3 p-5">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-primary-line bg-primary-bg text-primary">
                    <GraduationCap className="h-5 w-5" strokeWidth={1.8} />
                  </div>
                  <div className="flex flex-wrap justify-end gap-1.5">
                    {inst.is_registered && inst.verification_status === 'verified' && (
                      <Badge tone="good" size="sm">
                        <ShieldCheck className="h-3 w-3" strokeWidth={2.5} /> Verified
                      </Badge>
                    )}
                    {inst.is_registered && inst.verification_status !== 'verified' && (
                      <Badge tone="neutral" size="sm" withIcon={false}>
                        Registered
                      </Badge>
                    )}
                    {inst.institution_type && (
                      <Badge tone="primary" size="sm" withIcon={false}>
                        {inst.institution_type}
                      </Badge>
                    )}
                  </div>
                </div>
                <div>
                  <p className="text-[15px] font-bold text-ink">{inst.name}</p>
                  {(inst.location || inst.country) && (
                    <p className="mt-1 flex items-center gap-1 text-[12px] text-muted">
                      <MapPin className="h-3 w-3" strokeWidth={2} /> {inst.location ?? inst.country}
                    </p>
                  )}
                  {inst.description && <p className="mt-2 line-clamp-2 text-[13px] text-body">{inst.description}</p>}
                </div>
                <div className="mt-auto flex items-center gap-2 border-t border-white/5 pt-3">
                  <Link
                    to={`/student/institutions/${inst.id}`}
                    className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-[12px] font-semibold text-white transition-opacity hover:opacity-90"
                  >
                    View Institution <ArrowRight className="h-3.5 w-3.5" />
                  </Link>
                  {inst.website && (
                    <a
                      href={inst.website}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-line px-3 py-2 text-[12px] font-semibold text-body transition-colors hover:border-primary-line hover:text-ink"
                    >
                      <Globe className="h-3.5 w-3.5" strokeWidth={2} /> Website
                    </a>
                  )}
                </div>
              </GlassPanel>
            ))}
          </div>
          {result && <Pagination page={page} totalPages={result.totalPages} total={result.total} onPageChange={setPage} />}
        </>
      )}
    </div>
  )
}
