import { useEffect, useState } from 'react'
import { FileQuestion, CloudUpload, Lock, FolderOpen, FileText, Image, CheckCircle2, Hourglass, TriangleAlert, X } from 'lucide-react'
import { getMyDocuments, uploadStudentDocument } from '../../lib/api'
import { ApiError } from '../../lib/apiClient'
import { useAuth } from '../../context/AuthContext'
import type { CredentialType, StudentDocument, StudentDocumentStatus } from '../../types'
import { PageHeader, Button, GlassPanel } from '../../components/ui'
import { SkeletonGrid } from '../../components/ui/Skeleton'

/**
 * Reproduces Stitch's "upload_for_review" screen: a glass drag-drop-style
 * zone + encryption note on the left, a "Staging Area" list of documents on
 * the right (colored left-streak + mono status chip per item). Stitch's own
 * screen shows a multi-file client-side staging flow with fabricated file
 * names ("mit_transcript_2023.pdf", "stanford_id_front.jpg") and a fake
 * "0x8f...3a2" hash — the real upload flow here is one PDF at a time via the
 * existing handleSubmit/uploadStudentDocument call, and every list item below
 * renders the real StudentDocument the institution actually sees, never
 * Stitch's placeholder filenames or a fabricated on-chain reference.
 */

const TYPE_OPTIONS: { value: CredentialType; label: string }[] = [
  { value: 'degree', label: 'Degree' },
  { value: 'transcript', label: 'Transcript' },
  { value: 'migration', label: 'Migration Certificate' },
  { value: 'internship', label: 'Internship Certificate' },
  { value: 'certification', label: 'Certification' },
  { value: 'course', label: 'Course Completion' },
  { value: 'other', label: 'Other / Custom' },
]

const STATUS_ICON: Record<StudentDocumentStatus, typeof Hourglass> = {
  unverified: TriangleAlert,
  under_review: Hourglass,
  approved: CheckCircle2,
  rejected: X,
}

const STATUS_LABEL: Record<StudentDocumentStatus, string> = {
  unverified: 'Unverified',
  under_review: 'Under Review',
  approved: 'Approved',
  rejected: 'Rejected',
}

/** Left-streak + chip tone per status — mirrors Stitch's secondary/error/tertiary streak mapping. */
const STATUS_STREAK: Record<StudentDocumentStatus, string> = {
  unverified: 'from-bad to-bad/40',
  under_review: 'from-cyan to-primary',
  approved: 'from-good to-good/40',
  rejected: 'from-bad to-bad/40',
}
const STATUS_CHIP: Record<StudentDocumentStatus, string> = {
  unverified: 'bg-bad-bg border-bad-line text-bad',
  under_review: 'bg-cyan-bg border-cyan-line text-cyan',
  approved: 'bg-good-bg border-good-line text-good',
  rejected: 'bg-bad-bg border-bad-line text-bad',
}

export function Documents() {
  const { user } = useAuth()
  const [documents, setDocuments] = useState<StudentDocument[]>([])
  const [loading, setLoading] = useState(true)
  const [type, setType] = useState<CredentialType>('migration')
  const [customName, setCustomName] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function load() {
    getMyDocuments()
      .then(setDocuments)
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Unable to load your documents. Please try again.'))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    if (!user?.student_institution_id) {
      setError('Link your institution before uploading a document.')
      return
    }
    if (!file) {
      setError('Choose a PDF to upload.')
      return
    }
    setSubmitting(true)
    try {
      await uploadStudentDocument({
        institutionId: user.student_institution_id,
        credentialType: type,
        customCredentialName: type === 'other' ? customName : undefined,
        document: file,
      })
      setFile(null)
      setCustomName('')
      load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not upload this document.')
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return (
      <div>
        <PageHeader title="Upload for Review" eyebrow="Document Provenance" icon={FileQuestion} description=" " />
        <SkeletonGrid count={2} />
      </div>
    )
  }

  return (
    <div>
      <PageHeader
        title="Upload for Review"
        eyebrow="Document Provenance"
        icon={FileQuestion}
        description="Submit a document you already have for your institution to review and verify."
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Upload zone + encryption note */}
        <div className="flex flex-col gap-4 lg:col-span-2">
          <GlassPanel className="relative overflow-hidden p-6">
            <div aria-hidden className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_center,var(--color-primary-bg),transparent_70%)] opacity-60" />
            <form onSubmit={handleSubmit} className="relative space-y-4">
              <div className="flex min-h-[220px] flex-col items-center justify-center rounded-xl border-2 border-dashed border-line-strong px-6 py-8 text-center">
                <CloudUpload className="mb-3 h-12 w-12 text-faint" strokeWidth={1.5} />
                <h3 className="mb-1 text-base font-bold text-ink">Select a document to submit</h3>
                <p className="mb-5 max-w-sm text-[13px] text-muted">
                  PDF only. It stays Unverified until your institution reviews and approves it.
                </p>

                <div className="mb-4 flex flex-wrap items-center justify-center gap-3">
                  <select
                    value={type}
                    onChange={(e) => setType(e.target.value as CredentialType)}
                    className="rounded-lg border border-line bg-canvas-2 px-3.5 py-2 text-sm text-ink outline-none focus:border-electric"
                  >
                    {TYPE_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                  {type === 'other' && (
                    <input
                      value={customName}
                      onChange={(e) => setCustomName(e.target.value)}
                      placeholder="e.g. Bonafide Certificate"
                      className="rounded-lg border border-line bg-canvas-2 px-3.5 py-2 text-sm text-ink outline-none focus:border-electric"
                      required
                    />
                  )}
                </div>

                <label className="inline-flex cursor-pointer items-center gap-2 rounded-full bg-gradient-to-br from-primary to-ai px-6 py-2.5 text-[13px] font-semibold text-white shadow-glow-primary active:scale-95">
                  <FolderOpen className="h-4 w-4" strokeWidth={2} />
                  {file ? file.name : 'Browse Files'}
                  <input
                    type="file"
                    accept="application/pdf,.pdf"
                    onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                    className="hidden"
                    required
                  />
                </label>
              </div>

              {error && <div className="rounded-lg bg-bad-bg px-3.5 py-2.5 text-[13px] text-bad">{error}</div>}

              <Button type="submit" variant="solid" className="w-full" loading={submitting} disabled={!user?.student_institution_id}>
                Submit for Review
              </Button>
            </form>
          </GlassPanel>

          <GlassPanel className="flex items-start gap-4 p-4">
            <Lock className="mt-0.5 h-5 w-5 shrink-0 text-cyan" strokeWidth={2} />
            <div>
              <p className="mb-1 font-[family-name:var(--font-mono)] text-[11px] font-semibold uppercase tracking-wider text-ink">
                End-to-End Integrity
              </p>
              <p className="text-[13px] leading-relaxed text-muted">
                Once approved, the document is SHA-256 hashed and the credential is Ed25519-signed — the same
                cryptographic pipeline as an institution-issued credential.
              </p>
            </div>
          </GlassPanel>
        </div>

        {/* Staging area — real documents */}
        <div className="flex flex-col gap-3">
          <div className="mb-1 flex items-center justify-between">
            <h2 className="text-sm font-bold text-ink">Staging Area</h2>
            <span className="rounded bg-canvas-2 px-2 py-1 font-[family-name:var(--font-mono)] text-[11px] text-muted">
              {documents.length} {documents.length === 1 ? 'Item' : 'Items'}
            </span>
          </div>

          {documents.length === 0 ? (
            !error && (
              <GlassPanel className="flex flex-col items-center gap-2 p-6 text-center">
                <FileQuestion className="h-8 w-8 text-faint" strokeWidth={1.5} />
                <p className="text-[13px] text-muted">Documents you submit start as Unverified until your institution reviews them.</p>
              </GlassPanel>
            )
          ) : (
            documents.map((d) => {
              const StatusIcon = STATUS_ICON[d.status]
              const FileIcon = d.credential_type === 'other' ? Image : FileText
              return (
                <GlassPanel key={d.id} className="relative overflow-hidden p-4">
                  <div aria-hidden className={`absolute inset-y-0 left-0 w-1 bg-gradient-to-b ${STATUS_STREAK[d.status]} opacity-70`} />
                  <div className="flex items-start justify-between gap-3 pl-2">
                    <div className="flex items-center gap-3">
                      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-canvas-2">
                        <FileIcon className="h-4.5 w-4.5 text-muted" strokeWidth={2} />
                      </div>
                      <div className="min-w-0">
                        <p className="truncate text-[13px] font-semibold text-ink">
                          {d.credential_type === 'other' ? d.custom_credential_name : TYPE_OPTIONS.find((o) => o.value === d.credential_type)?.label}
                        </p>
                        <p className="font-[family-name:var(--font-mono)] text-[10px] text-faint">{d.institution_name}</p>
                      </div>
                    </div>
                  </div>
                  <div className="mt-3 flex items-center justify-between border-t border-line pt-3 pl-2">
                    <span className={`inline-flex items-center gap-1.5 rounded border px-2 py-1 font-[family-name:var(--font-mono)] text-[10px] uppercase tracking-wider ${STATUS_CHIP[d.status]}`}>
                      <StatusIcon className="h-3 w-3" strokeWidth={2.5} />
                      {STATUS_LABEL[d.status]}
                    </span>
                    {d.status === 'rejected' && d.rejection_reason && (
                      <span className="max-w-[55%] truncate text-[11px] text-bad" title={d.rejection_reason}>
                        {d.rejection_reason}
                      </span>
                    )}
                  </div>
                </GlassPanel>
              )
            })
          )}
        </div>
      </div>
    </div>
  )
}
