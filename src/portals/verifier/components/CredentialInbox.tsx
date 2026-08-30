import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Share2 } from 'lucide-react'
import { getSharedCredentialsPage } from '../../../lib/api'
import { ApiError } from '../../../lib/apiClient'
import type { SharedCredentialItem, SharedCredentialStatusFilter } from '../../../types'
import { GlassPanel, Badge, SearchInput, FilterPills, EmptyState, ErrorState, Pagination } from '../../../components/ui'
import { IconTile } from '../../../components/ui/IconTile'
import { SkeletonRow } from '../../../components/ui/Skeleton'
import { CREDENTIAL_TYPE_ICON } from '../../../lib/utils'

const PAGE_SIZE = 10

type FilterValue = 'all' | SharedCredentialStatusFilter

const FILTER_OPTIONS: { value: FilterValue; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'verified', label: 'Verified' },
  { value: 'invalid', label: 'Invalid' },
  { value: 'revoked', label: 'Revoked' },
  { value: 'expired', label: 'Expired' },
]

/** Real backend result -> badge. Never inferred from share/credential status alone (see backend/app/schemas/sharing.py's SharedCredentialItem docstring) — null genuinely means this company has never verified it. */
const RESULT_BADGE: Record<string, { tone: 'good' | 'bad' | 'warn' | 'neutral'; label: string }> = {
  VERIFIED: { tone: 'good', label: 'VERIFIED' },
  INVALID: { tone: 'bad', label: 'INVALID' },
  REVOKED: { tone: 'bad', label: 'REVOKED' },
  EXPIRED: { tone: 'warn', label: 'EXPIRED' },
  UNAUTHORIZED: { tone: 'bad', label: 'UNAUTHORIZED' },
  TYPE_MISMATCH: { tone: 'warn', label: 'TYPE MISMATCH' },
}

function statusBadge(result: SharedCredentialItem['latest_verification_result']) {
  if (!result) return { tone: 'neutral' as const, label: 'NOT VERIFIED' }
  return RESULT_BADGE[result] ?? { tone: 'neutral' as const, label: result }
}

function fmt(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
}

/**
 * "Credentials Shared With You" — a scalable inbox for the credentials a company
 * has actually been granted access to, backed by GET /api/companies/me/shared-credentials
 * (backend-paginated/searched/filtered, never the whole dataset — see
 * sharing_service.list_shared_credentials_for_company). Authorization is
 * unchanged: that endpoint is scoped to the logged-in company's own
 * canonical company_id exactly like every other company route, and a
 * directory-only company can never reach it at all (no login exists for
 * one). Clicking any card opens the existing verification page
 * (/verifier/verify/:id) — this component never re-implements verification,
 * it only displays the LAST real verification result on record, if any.
 */
export function CredentialInbox() {
  const [result, setResult] = useState<{ items: SharedCredentialItem[]; total: number; totalPages: number } | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<FilterValue>('all')
  const [page, setPage] = useState(1)
  const [retryToken, setRetryToken] = useState(0)

  // Any filter/search change resets to page 1 — adjusted during render, same pattern as
  // Companies.tsx / Institutions.tsx.
  const [prevFilters, setPrevFilters] = useState({ query, filter })
  if (prevFilters.query !== query || prevFilters.filter !== filter) {
    setPrevFilters({ query, filter })
    setPage(1)
  }

  useEffect(() => {
    const handle = setTimeout(() => {
      setLoading(true)
      setError(null)
      getSharedCredentialsPage({
        search: query.trim() || undefined,
        status: filter === 'all' ? undefined : filter,
        page,
        pageSize: PAGE_SIZE,
      })
        .then((data) => setResult({ items: data.items, total: data.total, totalPages: data.total_pages }))
        .catch((err) => setError(err instanceof ApiError ? err.message : 'Could not load shared credentials.'))
        .finally(() => setLoading(false))
    }, 300)
    return () => clearTimeout(handle)
  }, [query, filter, page, retryToken])

  return (
    <div>
      <h2 className="mb-1 text-[15px] font-bold text-ink">Credentials Shared With You</h2>
      <p className="mb-3 text-[13px] text-muted">Every credential a student has granted your company access to.</p>

      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <SearchInput
          placeholder="Search by student, credential, or institution…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="max-w-sm"
        />
        <FilterPills options={FILTER_OPTIONS} value={filter} onChange={setFilter} />
      </div>

      {error ? (
        <ErrorState description={error} onRetry={() => setRetryToken((t) => t + 1)} />
      ) : loading && !result ? (
        <div className="space-y-2.5">
          <SkeletonRow />
          <SkeletonRow />
          <SkeletonRow />
        </div>
      ) : result && result.items.length === 0 ? (
        <EmptyState
          icon={Share2}
          title="No shared credentials"
          description={query || filter !== 'all' ? 'No credentials match these filters.' : 'No credentials have been shared with your company yet.'}
        />
      ) : (
        <>
          <div className={loading ? 'space-y-2.5 opacity-60 transition-opacity' : 'space-y-2.5 transition-opacity'}>
            {result?.items.map((item) => {
              const badge = statusBadge(item.latest_verification_result)
              const Icon = CREDENTIAL_TYPE_ICON[item.credential_type]
              return (
                <Link key={`${item.share_id}-${item.id}`} to={`/verifier/verify/${item.id}`} className="block">
                  <GlassPanel className="flex items-center gap-4 p-4 transition-colors hover:border-primary-line">
                    <IconTile icon={Icon} tone="primary" size="sm" />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="truncate text-sm font-bold text-ink">{item.title}</p>
                        {item.share_status !== 'active' && (
                          <Badge tone="neutral" size="sm" withIcon={false}>
                            Share {item.share_status}
                          </Badge>
                        )}
                      </div>
                      <p className="truncate text-xs text-muted">
                        {item.student_name} · {item.institution_name}
                      </p>
                      <p className="mt-1 truncate text-[11px] text-faint">
                        Issued {fmt(item.issued_at)} · Shared {fmt(item.shared_at)}
                        {item.share_status === 'active' && ` · Access until ${fmt(item.share_expires_at)}`}
                      </p>
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-2">
                      <Badge tone={badge.tone} size="sm" withIcon={false}>
                        {badge.label}
                      </Badge>
                      <span className="text-[11px] font-semibold text-primary">
                        {item.latest_verification_result ? 'Re-verify' : 'Verify'} →
                      </span>
                    </div>
                  </GlassPanel>
                </Link>
              )
            })}
          </div>
          {result && <Pagination page={page} totalPages={result.totalPages} total={result.total} onPageChange={setPage} />}
        </>
      )}
    </div>
  )
}
