import { useEffect, useMemo, useState } from 'react'
import { ClipboardList } from 'lucide-react'
import { createCertificateRequestBatch, getMyCertificateRequests } from '../../lib/api'
import { ApiError } from '../../lib/apiClient'
import { useAuth } from '../../context/AuthContext'
import type { CredentialType, InstitutionCertificateRequest, InstitutionRequestStatus } from '../../types'
import { PageHeader, Card, Button, Badge, EmptyState, WorkflowTimeline, buildCertificateRequestSteps } from '../../components/ui'
import { SkeletonGrid } from '../../components/ui/Skeleton'

const TYPE_OPTIONS: { value: CredentialType; label: string }[] = [
  { value: 'degree', label: 'Degree Certificate' },
  { value: 'transcript', label: 'Transcript' },
  { value: 'migration', label: 'Migration Certificate' },
  { value: 'internship', label: 'Internship Certificate' },
  { value: 'certification', label: 'Certification' },
  { value: 'course', label: 'Course Completion' },
  { value: 'other', label: 'Other / Custom' },
]

const STATUS_TONE: Record<InstitutionRequestStatus, 'good' | 'warn' | 'bad' | 'neutral'> = {
  pending: 'warn',
  approved: 'good',
  rejected: 'bad',
  fulfilled: 'good',
}

function typeLabel(r: InstitutionCertificateRequest): string {
  return r.credential_type === 'other' ? (r.custom_credential_name ?? 'Other') : (TYPE_OPTIONS.find((o) => o.value === r.credential_type)?.label ?? r.credential_type)
}

interface RequestGroup {
  key: string
  reason: string | null
  items: InstitutionCertificateRequest[]
}

function groupRequests(requests: InstitutionCertificateRequest[]): RequestGroup[] {
  const groups = new Map<string, RequestGroup>()
  for (const r of requests) {
    const key = r.batch_id ?? r.id
    const existing = groups.get(key)
    if (existing) {
      existing.items.push(r)
    } else {
      groups.set(key, { key, reason: r.reason, items: [r] })
    }
  }
  return Array.from(groups.values()).sort(
    (a, b) => new Date(b.items[0].created_at).getTime() - new Date(a.items[0].created_at).getTime()
  )
}

export function CertificateRequests() {
  const { user } = useAuth()
  const [requests, setRequests] = useState<InstitutionCertificateRequest[]>([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [selected, setSelected] = useState<Set<CredentialType>>(new Set(['transcript']))
  const [customName, setCustomName] = useState('')
  const [reason, setReason] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function load() {
    getMyCertificateRequests()
      .then(setRequests)
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Unable to load certificate requests. Please try again.'))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  const groups = useMemo(() => groupRequests(requests), [requests])

  function toggle(type: CredentialType) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(type)) next.delete(type)
      else next.add(type)
      return next
    })
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    if (!user?.student_institution_id) {
      setError('Link your institution before requesting a certificate.')
      return
    }
    if (selected.size === 0) {
      setError('Select at least one document to request.')
      return
    }
    setSubmitting(true)
    try {
      await createCertificateRequestBatch({
        institutionId: user.student_institution_id,
        items: Array.from(selected).map((credentialType) => ({
          credentialType,
          customCredentialName: credentialType === 'other' ? customName : undefined,
        })),
        reason: reason || undefined,
      })
      setShowForm(false)
      setReason('')
      setCustomName('')
      setSelected(new Set(['transcript']))
      load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not submit this request.')
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return (
      <div>
        <PageHeader title="Request from Institution" eyebrow="Certificate Requests" icon={ClipboardList} description=" " />
        <SkeletonGrid count={2} />
      </div>
    )
  }

  return (
    <div>
      <PageHeader
        title="Request from Institution"
        eyebrow="Certificate Requests"
        icon={ClipboardList}
        description="Request one or more certificates directly from your institution."
      />

      <div className="mb-5">
        {!showForm ? (
          <Button variant="solid" onClick={() => setShowForm(true)} disabled={!user?.student_institution_id}>
            Request Certificates
          </Button>
        ) : (
          <Card className="max-w-lg p-6">
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="mb-1.5 block text-[10px] font-bold uppercase tracking-wider text-faint">Documents to request</label>
                <div className="space-y-2">
                  {TYPE_OPTIONS.map((o) => (
                    <label
                      key={o.value}
                      className="flex cursor-pointer items-center gap-3 rounded-lg border border-line px-3.5 py-2.5 hover:bg-canvas-2/60"
                    >
                      <input
                        type="checkbox"
                        checked={selected.has(o.value)}
                        onChange={() => toggle(o.value)}
                        className="h-4 w-4 rounded border-line accent-primary"
                      />
                      <span className="text-sm font-medium text-ink">{o.label}</span>
                    </label>
                  ))}
                </div>
              </div>

              {selected.has('other') && (
                <div>
                  <label className="mb-1.5 block text-[10px] font-bold uppercase tracking-wider text-faint">Custom credential name</label>
                  <input
                    value={customName}
                    onChange={(e) => setCustomName(e.target.value)}
                    placeholder="e.g. Bonafide Certificate"
                    className="w-full rounded-lg border border-line bg-surface px-3.5 py-2.5 text-sm text-ink outline-none focus:border-primary"
                    required
                  />
                </div>
              )}

              <div>
                <label className="mb-1.5 block text-[10px] font-bold uppercase tracking-wider text-faint">Reason / purpose (optional)</label>
                <textarea
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  rows={3}
                  className="w-full rounded-lg border border-line bg-surface px-3.5 py-2.5 text-sm text-ink outline-none focus:border-primary"
                />
              </div>

              {error && <div className="rounded-lg bg-bad-bg px-3.5 py-2.5 text-[13px] text-bad">{error}</div>}

              <div className="flex gap-3">
                <Button type="button" variant="outline" onClick={() => setShowForm(false)}>
                  Cancel
                </Button>
                <Button type="submit" variant="solid" loading={submitting} disabled={selected.size === 0}>
                  Submit Request{selected.size > 1 ? ` (${selected.size})` : ''}
                </Button>
              </div>
            </form>
          </Card>
        )}
      </div>

      {error && !showForm && <div className="mb-5 max-w-lg rounded-lg bg-bad-bg px-3.5 py-2.5 text-[13px] text-bad">{error}</div>}

      {groups.length === 0 ? (
        !error && (
          <EmptyState
            icon={ClipboardList}
            title="No certificate requests yet"
            description="Request a transcript, degree, or other certificate directly from your institution."
          />
        )
      ) : (
        <div className="space-y-3">
          {groups.map((g) => (
            <Card key={g.key} className="max-w-2xl p-5">
              {g.reason && <p className="mb-2 text-xs text-muted">{g.reason}</p>}
              <div className="space-y-2">
                {g.items.map((r) => (
                  <div key={r.id} className="rounded-lg border border-line px-3.5 py-3">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <p className="text-sm font-semibold text-ink">{typeLabel(r)}</p>
                        <p className="text-[11px] text-faint">{r.institution_name}</p>
                      </div>
                      <Badge tone={STATUS_TONE[r.status]} size="sm">
                        {r.status}
                      </Badge>
                    </div>
                    <div className="mt-3 border-t border-line/60 pt-3">
                      <WorkflowTimeline steps={buildCertificateRequestSteps(r)} />
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
