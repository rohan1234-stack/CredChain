import { useEffect, useState } from 'react'
import { ShieldCheck, Landmark, Building2, Check, X } from 'lucide-react'
import {
  getPendingInstitutions,
  getPendingCompanies,
  approveInstitutionVerification,
  rejectInstitutionVerification,
  approveCompanyVerification,
  rejectCompanyVerification,
} from '../../lib/api'
import { ApiError } from '../../lib/apiClient'
import type { PendingInstitution, PendingCompany } from '../../types'
import { PageHeader, Card, Button, Badge, EmptyState, Modal, SearchInput, Pagination } from '../../components/ui'
import { SkeletonCard } from '../../components/ui/Skeleton'
import { Textarea } from '../../components/ui/Input'

const PAGE_SIZE = 12

/**
 * Phase A's entire admin surface: two independent verification queues (institutions,
 * companies), each a real GET /api/admin/.../pending + approve/reject action — nothing else.
 * No analytics, no user management, no support tooling (explicitly out of scope for Phase A).
 * Both queues are backend-paginated/searched (see admin_service.list_pending_institutions/
 * list_pending_companies) — never loads the entire pending table into the browser, same pattern
 * as every other directory listing in the app (Companies.tsx, Institutions.tsx, CredentialInbox.tsx).
 */
export function AdminDashboard() {
  return (
    <div className="space-y-8">
      <PageHeader
        title="Verification"
        eyebrow="Admin"
        icon={ShieldCheck}
        description="Review registered institution and company accounts before they can issue credentials or publish jobs."
      />
      <InstitutionQueue />
      <CompanyQueue />
    </div>
  )
}

function InstitutionQueue() {
  const [result, setResult] = useState<{ items: PendingInstitution[]; total: number; totalPages: number } | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [rejectingId, setRejectingId] = useState<string | null>(null)
  const [reason, setReason] = useState('')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)
  const [retryToken, setRetryToken] = useState(0)

  // Search change resets to page 1 — same render-time-reset pattern as Companies.tsx/Institutions.tsx.
  const [prevQuery, setPrevQuery] = useState(query)
  if (prevQuery !== query) {
    setPrevQuery(query)
    setPage(1)
  }

  useEffect(() => {
    const handle = setTimeout(() => {
      setLoading(true)
      setError(null)
      getPendingInstitutions({ search: query.trim() || undefined, page, pageSize: PAGE_SIZE })
        .then((data) => {
          // Approving/rejecting the last item on a page beyond the first would otherwise leave
          // an empty page with real results still on earlier pages — step back instead.
          if (data.items.length === 0 && page > 1 && data.total > 0) {
            setPage((p) => Math.max(1, p - 1))
            return
          }
          setResult({ items: data.items, total: data.total, totalPages: data.total_pages })
        })
        .catch((err) => setError(err instanceof ApiError ? err.message : 'Unable to load pending institutions. Please try again.'))
        .finally(() => setLoading(false))
    }, 300)
    return () => clearTimeout(handle)
  }, [query, page, retryToken])

  const items = result?.items ?? []

  async function handleApprove(id: string) {
    setBusyId(id)
    setError(null)
    try {
      await approveInstitutionVerification(id)
      setRetryToken((t) => t + 1)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not approve this institution.')
    } finally {
      setBusyId(null)
    }
  }

  async function handleReject(id: string) {
    if (!reason.trim()) return
    setBusyId(id)
    setError(null)
    try {
      await rejectInstitutionVerification(id, reason.trim())
      setRejectingId(null)
      setReason('')
      setRetryToken((t) => t + 1)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not reject this institution.')
    } finally {
      setBusyId(null)
    }
  }

  return (
    <section>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-faint">
          <Landmark className="h-4 w-4" /> Pending Institutions
          {result && <Badge tone="neutral" size="sm" withIcon={false}>{result.total}</Badge>}
        </h2>
        <SearchInput placeholder="Search by name…" value={query} onChange={(e) => setQuery(e.target.value)} className="max-w-xs" />
      </div>

      {error && <div className="mb-4 max-w-2xl rounded-lg bg-bad-bg px-3.5 py-2.5 text-[13px] text-bad">{error}</div>}

      {loading && !result ? (
        <div className="space-y-3"><SkeletonCard lines={2} /></div>
      ) : items.length === 0 ? (
        !error && (
          <EmptyState
            icon={Landmark}
            title="No pending institutions"
            description={query ? 'No pending institutions match this search.' : 'Every registered institution has already been reviewed.'}
          />
        )
      ) : (
        <>
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          {items.map((i) => (
            <Card key={i.id} className="p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-bold text-ink">{i.name}</p>
                  <p className="truncate text-[12px] text-muted">{i.contact_email ?? 'No contact email on file'}</p>
                  {i.location && <p className="mt-0.5 text-[11px] text-faint">{i.location}</p>}
                  {i.website && (
                    <a href={i.website} target="_blank" rel="noopener noreferrer" className="text-[11px] text-cyan hover:underline">
                      {i.website}
                    </a>
                  )}
                </div>
                <Badge tone="warn" size="sm" withIcon={false}>
                  Pending
                </Badge>
              </div>
              <div className="mt-3 flex gap-2 border-t border-line pt-3">
                <Button variant="solid" size="sm" icon={<Check className="h-3.5 w-3.5" />} loading={busyId === i.id} onClick={() => handleApprove(i.id)}>
                  Approve
                </Button>
                <Button variant="outline" size="sm" icon={<X className="h-3.5 w-3.5" />} disabled={busyId === i.id} onClick={() => { setRejectingId(i.id); setReason('') }}>
                  Reject
                </Button>
              </div>
            </Card>
          ))}
        </div>
        {result && <Pagination page={page} totalPages={result.totalPages} total={result.total} onPageChange={setPage} />}
        </>
      )}

      <Modal open={rejectingId !== null} onClose={() => setRejectingId(null)} title="Reject institution" size="sm">
        <div className="space-y-3">
          <p className="text-[13px] text-muted">This institution will not be able to issue credentials. Give a reason (shown to the account owner).</p>
          <Textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} placeholder="e.g. Registration number could not be verified" />
          <div className="flex justify-end gap-2">
            <Button variant="outline" size="sm" onClick={() => setRejectingId(null)}>
              Cancel
            </Button>
            <Button variant="danger" size="sm" disabled={!reason.trim()} loading={busyId === rejectingId} onClick={() => rejectingId && handleReject(rejectingId)}>
              Confirm Reject
            </Button>
          </div>
        </div>
      </Modal>
    </section>
  )
}

function CompanyQueue() {
  const [result, setResult] = useState<{ items: PendingCompany[]; total: number; totalPages: number } | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [rejectingId, setRejectingId] = useState<string | null>(null)
  const [reason, setReason] = useState('')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)
  const [retryToken, setRetryToken] = useState(0)

  const [prevQuery, setPrevQuery] = useState(query)
  if (prevQuery !== query) {
    setPrevQuery(query)
    setPage(1)
  }

  useEffect(() => {
    const handle = setTimeout(() => {
      setLoading(true)
      setError(null)
      getPendingCompanies({ search: query.trim() || undefined, page, pageSize: PAGE_SIZE })
        .then((data) => {
          if (data.items.length === 0 && page > 1 && data.total > 0) {
            setPage((p) => Math.max(1, p - 1))
            return
          }
          setResult({ items: data.items, total: data.total, totalPages: data.total_pages })
        })
        .catch((err) => setError(err instanceof ApiError ? err.message : 'Unable to load pending companies. Please try again.'))
        .finally(() => setLoading(false))
    }, 300)
    return () => clearTimeout(handle)
  }, [query, page, retryToken])

  const items = result?.items ?? []

  async function handleApprove(id: string) {
    setBusyId(id)
    setError(null)
    try {
      await approveCompanyVerification(id)
      setRetryToken((t) => t + 1)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not approve this company.')
    } finally {
      setBusyId(null)
    }
  }

  async function handleReject(id: string) {
    if (!reason.trim()) return
    setBusyId(id)
    setError(null)
    try {
      await rejectCompanyVerification(id, reason.trim())
      setRejectingId(null)
      setReason('')
      setRetryToken((t) => t + 1)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not reject this company.')
    } finally {
      setBusyId(null)
    }
  }

  return (
    <section>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-faint">
          <Building2 className="h-4 w-4" /> Pending Companies
          {result && <Badge tone="neutral" size="sm" withIcon={false}>{result.total}</Badge>}
        </h2>
        <SearchInput placeholder="Search by name…" value={query} onChange={(e) => setQuery(e.target.value)} className="max-w-xs" />
      </div>

      {error && <div className="mb-4 max-w-2xl rounded-lg bg-bad-bg px-3.5 py-2.5 text-[13px] text-bad">{error}</div>}

      {loading && !result ? (
        <div className="space-y-3"><SkeletonCard lines={2} /></div>
      ) : items.length === 0 ? (
        !error && (
          <EmptyState
            icon={Building2}
            title="No pending companies"
            description={query ? 'No pending companies match this search.' : 'Every registered company has already been reviewed.'}
          />
        )
      ) : (
        <>
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          {items.map((c) => (
            <Card key={c.id} className="p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-bold text-ink">{c.name}</p>
                  <p className="truncate text-[12px] text-muted">{c.contact_email ?? 'No contact email on file'}</p>
                  {c.industry && <p className="mt-0.5 text-[11px] text-faint">{c.industry}</p>}
                  {c.website && (
                    <a href={c.website} target="_blank" rel="noopener noreferrer" className="text-[11px] text-cyan hover:underline">
                      {c.website}
                    </a>
                  )}
                </div>
                <Badge tone="warn" size="sm" withIcon={false}>
                  Pending
                </Badge>
              </div>
              <div className="mt-3 flex gap-2 border-t border-line pt-3">
                <Button variant="solid" size="sm" icon={<Check className="h-3.5 w-3.5" />} loading={busyId === c.id} onClick={() => handleApprove(c.id)}>
                  Approve
                </Button>
                <Button variant="outline" size="sm" icon={<X className="h-3.5 w-3.5" />} disabled={busyId === c.id} onClick={() => { setRejectingId(c.id); setReason('') }}>
                  Reject
                </Button>
              </div>
            </Card>
          ))}
        </div>
        {result && <Pagination page={page} totalPages={result.totalPages} total={result.total} onPageChange={setPage} />}
        </>
      )}

      <Modal open={rejectingId !== null} onClose={() => setRejectingId(null)} title="Reject company" size="sm">
        <div className="space-y-3">
          <p className="text-[13px] text-muted">This company will not be able to publish jobs. Give a reason (shown to the account owner).</p>
          <Textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} placeholder="e.g. Company website could not be verified" />
          <div className="flex justify-end gap-2">
            <Button variant="outline" size="sm" onClick={() => setRejectingId(null)}>
              Cancel
            </Button>
            <Button variant="danger" size="sm" disabled={!reason.trim()} loading={busyId === rejectingId} onClick={() => rejectingId && handleReject(rejectingId)}>
              Confirm Reject
            </Button>
          </div>
        </div>
      </Modal>
    </section>
  )
}
