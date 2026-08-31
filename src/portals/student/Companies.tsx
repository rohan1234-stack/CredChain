import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Building2, MapPin, Briefcase, ArrowRight, Globe, ShieldCheck } from 'lucide-react'
import { getCompaniesPage } from '../../lib/api'
import { ApiError } from '../../lib/apiClient'
import type { Company } from '../../types'
import { PageHeader, SearchInput, GlassPanel, EmptyState, ErrorState, Badge, Pagination } from '../../components/ui'
import { SkeletonCard } from '../../components/ui/Skeleton'
import { InitialsAvatar } from '../../components/ui/IconTile'
import { COUNTRIES } from '../../lib/countries'

const PAGE_SIZE = 24

/**
 * Student Company Directory — bento glass-card grid (see career_opportunities
 * / Jobs.tsx). Fully backend-paginated/searched (GET /api/companies?search=
 * &industry=&country=&page=...) so this scales to a globally-imported
 * dataset without ever fetching more than one page's worth into the browser.
 */
function initialsOf(name: string) {
  return (
    name
      .split(' ')
      .map((w) => w[0])
      .filter(Boolean)
      .slice(0, 2)
      .join('')
      .toUpperCase() || '?'
  )
}

export function Companies() {
  const [result, setResult] = useState<{ items: Company[]; total: number; totalPages: number } | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [industry, setIndustry] = useState('')
  const [country, setCountry] = useState('')
  const [page, setPage] = useState(1)
  const [retryToken, setRetryToken] = useState(0)

  // Any filter change resets to page 1 — adjusted during render (React's documented pattern)
  // rather than a separate effect, same as Institutions.tsx.
  const [prevFilters, setPrevFilters] = useState({ query, industry, country })
  if (prevFilters.query !== query || prevFilters.industry !== industry || prevFilters.country !== country) {
    setPrevFilters({ query, industry, country })
    setPage(1)
  }

  // "Latest request wins" sequence guard — same pattern as OrgPicker in SignUp.tsx. Without
  // this, a slow, stale response (e.g. from a shorter, earlier-paused query) can resolve after
  // a newer one and overwrite its correct results.
  const requestSeqRef = useRef(0)

  useEffect(() => {
    const seq = ++requestSeqRef.current
    const handle = setTimeout(() => {
      setLoading(true)
      setError(null)
      getCompaniesPage({
        search: query.trim() || undefined,
        industry: industry.trim() || undefined,
        country: country || undefined,
        page,
        pageSize: PAGE_SIZE,
      })
        .then((data) => {
          if (seq !== requestSeqRef.current) return // a newer search superseded this one
          setResult({ items: data.items, total: data.total, totalPages: data.total_pages })
        })
        .catch((err) => {
          if (seq !== requestSeqRef.current) return
          setError(err instanceof ApiError ? err.message : 'Could not load companies.')
        })
        .finally(() => {
          if (seq === requestSeqRef.current) setLoading(false)
        })
    }, 300)
    return () => clearTimeout(handle)
  }, [query, industry, country, page, retryToken])

  return (
    <div>
      <PageHeader title="Companies" eyebrow="Professional Discovery" icon={Building2} description="Discover companies from around the world." />

      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center">
        <SearchInput placeholder="Search companies…" value={query} onChange={(e) => setQuery(e.target.value)} className="max-w-xs" />
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
          placeholder="Industry…"
          value={industry}
          onChange={(e) => setIndustry(e.target.value)}
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
          icon={Building2}
          title="No companies found"
          description={query || industry || country ? 'No companies match these filters.' : 'No companies are in the directory yet.'}
        />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {result?.items.map((c) => (
              <GlassPanel key={c.id} className="flex flex-col gap-3 p-5">
                <div className="flex items-start justify-between gap-3">
                  <InitialsAvatar initials={initialsOf(c.name)} tone="ink" />
                  {c.is_registered && c.verification_status === 'verified' && (
                    <Badge tone="good" size="sm">
                      <ShieldCheck className="h-3 w-3" strokeWidth={2.5} /> Verified
                    </Badge>
                  )}
                  {c.is_registered && c.verification_status !== 'verified' && (
                    <Badge tone="neutral" size="sm" withIcon={false}>
                      Registered
                    </Badge>
                  )}
                </div>
                <div>
                  <p className="text-[15px] font-bold text-ink">{c.name}</p>
                  <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-muted">
                    {c.industry && (
                      <span className="flex items-center gap-1">
                        <Briefcase className="h-3 w-3" strokeWidth={2} /> {c.industry}
                      </span>
                    )}
                    {(c.location || c.country) && (
                      <span className="flex items-center gap-1">
                        <MapPin className="h-3 w-3" strokeWidth={2} /> {c.location ?? c.country}
                      </span>
                    )}
                  </div>
                  {c.open_positions_count > 0 && (
                    <p className="mt-2 text-[12px] font-semibold text-good">
                      {c.open_positions_count} open position{c.open_positions_count === 1 ? '' : 's'}
                    </p>
                  )}
                </div>
                <div className="mt-auto flex items-center gap-2 border-t border-white/5 pt-3">
                  <Link
                    to={`/student/companies/${c.id}`}
                    className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-[12px] font-semibold text-white transition-opacity hover:opacity-90"
                  >
                    View Company <ArrowRight className="h-3.5 w-3.5" />
                  </Link>
                  {c.website && (
                    <a
                      href={c.website}
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
