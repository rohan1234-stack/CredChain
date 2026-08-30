import { useEffect, useState } from 'react'
import { ShieldQuestion, FileText } from 'lucide-react'
import { approveStudentDocument, getInstitutionDocumentFile, getInstitutionDocuments, rejectStudentDocument } from '../../lib/api'
import { ApiError } from '../../lib/apiClient'
import type { StudentDocument, StudentDocumentStatus } from '../../types'
import { PageHeader, Card, Button, Badge, EmptyState, Field } from '../../components/ui'
import { Input } from '../../components/ui/Input'
import { SkeletonCard } from '../../components/ui/Skeleton'
import { CREDENTIAL_TYPE_ICON } from '../../lib/utils'

/** Only these document types plausibly carry a degree/CGPA/graduation-year value worth confirming — mirrors IssueCredential.tsx's own type gating. */
function carriesAcademicMetadata(type: string): boolean {
  return type === 'degree' || type === 'transcript'
}

const TYPE_LABELS: Record<string, string> = {
  degree: 'Degree',
  transcript: 'Transcript',
  migration: 'Migration Certificate',
  internship: 'Internship Certificate',
  certification: 'Certification',
  course: 'Course Completion',
}

const STATUS_TONE: Record<StudentDocumentStatus, 'good' | 'warn' | 'bad' | 'neutral'> = {
  unverified: 'neutral',
  under_review: 'warn',
  approved: 'good',
  rejected: 'bad',
}

/** Left-rail accent so the four provenance states (UNVERIFIED -> UNDER REVIEW ->
 * APPROVED/ISSUED or REJECTED) read as visually distinct at a glance, not just by badge text. */
const STATUS_RAIL: Record<StudentDocumentStatus, string> = {
  unverified: 'border-l-line-strong',
  under_review: 'border-l-warn',
  approved: 'border-l-good',
  rejected: 'border-l-bad',
}

const STATUS_LABEL: Record<StudentDocumentStatus, string> = {
  unverified: 'Unverified',
  under_review: 'Under Review',
  approved: 'Approved',
  rejected: 'Rejected',
}

export function DocumentReview() {
  const [documents, setDocuments] = useState<StudentDocument[]>([])
  const [loading, setLoading] = useState(true)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [rejectingId, setRejectingId] = useState<string | null>(null)
  const [rejectReason, setRejectReason] = useState('')
  const [viewingId, setViewingId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [approvingId, setApprovingId] = useState<string | null>(null)
  const [approveDegree, setApproveDegree] = useState('')
  const [approveGradYear, setApproveGradYear] = useState('')
  const [approveCgpa, setApproveCgpa] = useState('')

  function load() {
    getInstitutionDocuments()
      .then(setDocuments)
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Unable to load documents. Please try again.'))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  function typeLabel(d: StudentDocument) {
    return d.credential_type === 'other' ? d.custom_credential_name : TYPE_LABELS[d.credential_type]
  }

  async function handleApprove(id: string) {
    setBusyId(id)
    setError(null)
    try {
      const updated = await approveStudentDocument(id, {
        degree: approveDegree.trim() || undefined,
        graduationYear: approveGradYear ? Number(approveGradYear) : undefined,
        cgpa: approveCgpa ? Number(approveCgpa) : undefined,
      })
      setDocuments((prev) => prev.map((d) => (d.id === id ? updated : d)))
      setApprovingId(null)
      setApproveDegree('')
      setApproveGradYear('')
      setApproveCgpa('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not approve this document.')
    } finally {
      setBusyId(null)
    }
  }

  async function handleReject(id: string) {
    if (!rejectReason.trim()) return
    setBusyId(id)
    setError(null)
    try {
      const updated = await rejectStudentDocument(id, rejectReason)
      setDocuments((prev) => prev.map((d) => (d.id === id ? updated : d)))
      setRejectingId(null)
      setRejectReason('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not reject this document.')
    } finally {
      setBusyId(null)
    }
  }

  async function handleView(id: string) {
    setViewingId(id)
    setError(null)
    try {
      const blob = await getInstitutionDocumentFile(id)
      const url = URL.createObjectURL(blob)
      window.open(url, '_blank')
      setTimeout(() => URL.revokeObjectURL(url), 30_000)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not load the document.')
    } finally {
      setViewingId(null)
    }
  }

  if (loading) return <div className="space-y-4"><SkeletonCard lines={3} /><SkeletonCard lines={3} /></div>

  return (
    <div>
      <PageHeader title="Document Verification Requests" eyebrow="Provenance Review" icon={ShieldQuestion} description="Documents students have uploaded for your institution to review." />

      {error && <div className="mb-5 max-w-2xl rounded-lg bg-bad-bg px-3.5 py-2.5 text-[13px] text-bad">{error}</div>}

      {documents.length === 0 ? (
        !error && <EmptyState icon={ShieldQuestion} title="No documents to review" description="When a student uploads an existing document, it will show up here." />
      ) : (
        <div className="space-y-3">
          {documents.map((d) => (
            <Card key={d.id} className={`relative max-w-2xl overflow-hidden border-l-[3px] p-5 ${STATUS_RAIL[d.status]}`}>
              {d.status === 'under_review' && (
                <div aria-hidden className="pointer-events-none absolute -right-10 -top-10 h-32 w-32 rounded-full bg-warn/10 blur-2xl" />
              )}
              <div className="relative flex items-center justify-between gap-3">
                <div>
                  <p className="text-lg font-bold text-ink">{d.student_name}</p>
                  <p className="mt-0.5 text-xs text-muted">Submitted {new Date(d.created_at).toLocaleDateString()}</p>
                </div>
                <Badge tone={STATUS_TONE[d.status]}>
                  {d.status === 'under_review' && (
                    <span className="relative mr-0.5 flex h-1.5 w-1.5">
                      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-warn opacity-75" />
                      <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-warn" />
                    </span>
                  )}
                  {STATUS_LABEL[d.status]}
                </Badge>
              </div>

              <div className="relative mt-4 flex items-center gap-2 border-t border-line pt-4">
                {(() => {
                  const Icon = CREDENTIAL_TYPE_ICON[d.credential_type] ?? FileText
                  return <Icon className="h-4 w-4 text-primary" strokeWidth={2} />
                })()}
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-wider text-faint">Document Type</p>
                  <p className="text-sm text-body">
                    {typeLabel(d)} · {d.student_identifier}
                  </p>
                </div>
              </div>

              {(d.status === 'unverified' || d.status === 'under_review') && (
                <div className="mt-4">
                  <Button
                    variant="outline"
                    size="sm"
                    className="mb-3"
                    loading={viewingId === d.id}
                    onClick={() => handleView(d.id)}
                  >
                    View uploaded PDF
                  </Button>
                  {rejectingId === d.id ? (
                    <div className="space-y-2">
                      <textarea
                        value={rejectReason}
                        onChange={(e) => setRejectReason(e.target.value)}
                        placeholder="Reason for rejection"
                        rows={2}
                        className="w-full rounded-lg border border-line bg-surface px-3.5 py-2.5 text-sm text-ink outline-none focus:border-primary"
                      />
                      <div className="flex gap-2">
                        <Button variant="outline" size="sm" onClick={() => setRejectingId(null)}>
                          Cancel
                        </Button>
                        <Button variant="solid" size="sm" loading={busyId === d.id} onClick={() => handleReject(d.id)}>
                          Confirm Reject
                        </Button>
                      </div>
                    </div>
                  ) : approvingId === d.id && carriesAcademicMetadata(d.credential_type) ? (
                    <div className="space-y-3 rounded-lg border border-line bg-canvas-2/40 p-3.5">
                      <p className="text-[10px] font-bold uppercase tracking-wider text-faint">Cryptographic Metadata</p>
                      <p className="text-[12px] leading-relaxed text-muted">
                        Confirm the academic details shown on the document — this becomes the credential&rsquo;s real,
                        signed metadata (never left blank just because the file wasn&rsquo;t typed in).
                      </p>
                      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                        <div className="relative border-l-2 border-cyan/40 pl-3">
                          <Field label="Degree">
                            <Input value={approveDegree} onChange={(e) => setApproveDegree(e.target.value)} placeholder="e.g. B.Tech Computer Science" />
                          </Field>
                        </div>
                        <div className="relative border-l-2 border-cyan/40 pl-3">
                          <Field label="Graduation year">
                            <Input type="number" min="1950" max="2100" value={approveGradYear} onChange={(e) => setApproveGradYear(e.target.value)} />
                          </Field>
                        </div>
                        <div className="relative border-l-2 border-cyan/40 pl-3">
                          <Field label="CGPA">
                            <Input type="number" step="0.1" min="0" max="10" value={approveCgpa} onChange={(e) => setApproveCgpa(e.target.value)} />
                          </Field>
                        </div>
                      </div>
                      <div className="flex gap-2">
                        <Button variant="outline" size="sm" onClick={() => setApprovingId(null)}>
                          Cancel
                        </Button>
                        <Button variant="solid" size="sm" loading={busyId === d.id} onClick={() => handleApprove(d.id)}>
                          Confirm &amp; Sign
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <div className="flex gap-3">
                      <Button variant="outline" onClick={() => setRejectingId(d.id)}>
                        Reject
                      </Button>
                      <Button
                        variant="solid"
                        loading={busyId === d.id}
                        onClick={() => (carriesAcademicMetadata(d.credential_type) ? setApprovingId(d.id) : handleApprove(d.id))}
                      >
                        Approve &amp; Sign
                      </Button>
                    </div>
                  )}
                </div>
              )}
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
