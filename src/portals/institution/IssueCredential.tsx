import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Search, Check, X, ShieldCheck, User, FileText, GraduationCap, Upload, Send, Fingerprint, Lock, School, BarChart3, CalendarDays } from 'lucide-react'
import { getStudents, getStudentByIdentifier, issueCredential, bulkIssueCredentials, type BulkIssuanceItemResult } from '../../lib/api'
import { ApiError } from '../../lib/apiClient'
import type { CredentialType } from '../../types'
import { PageHeader, Card, Button, Badge, Field, GlassPanel } from '../../components/ui'
import { IconTile } from '../../components/ui/IconTile'
import { Input, Select } from '../../components/ui/Input'

const STEPS = [
  { key: 'student', label: 'Student', icon: User },
  { key: 'credential', label: 'Credential', icon: FileText },
  { key: 'details', label: 'Details', icon: GraduationCap },
  { key: 'document', label: 'Document', icon: Upload },
  { key: 'issue', label: 'Issue', icon: Send },
] as const

const TYPE_OPTIONS: { value: CredentialType; label: string }[] = [
  { value: 'degree', label: 'Degree' },
  { value: 'transcript', label: 'Transcript' },
  { value: 'migration', label: 'Migration Certificate' },
  { value: 'internship', label: 'Internship Certificate' },
  { value: 'certification', label: 'Certification' },
  { value: 'course', label: 'Course Completion' },
  { value: 'other', label: 'Other / Custom' },
]

type Student = { id: string; name: string; identifier: string }

export function IssueCredential() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const prefillStudentId = searchParams.get('studentId')
  const prefillType = searchParams.get('credentialType') as CredentialType | null
  const fulfillsRequestId = searchParams.get('fulfillsRequestId')

  const [issueMode, setIssueMode] = useState<'single' | 'bulk'>('single')

  const [students, setStudents] = useState<Student[]>([])
  const [studentsLoaded, setStudentsLoaded] = useState(false)
  const [studentId, setStudentId] = useState('')
  const [studentSearch, setStudentSearch] = useState('')

  const [studentMode, setStudentMode] = useState<'select' | 'manual'>('select')
  const [manualIdentifier, setManualIdentifier] = useState('')
  const [manualLookupState, setManualLookupState] = useState<'idle' | 'loading' | 'found' | 'not-found'>('idle')
  const [manualStudentName, setManualStudentName] = useState('')

  // Bulk mode: which students are checked, and each checked student's own file.
  const [bulkSelected, setBulkSelected] = useState<Set<string>>(new Set())
  const [bulkDocuments, setBulkDocuments] = useState<Record<string, File | null>>({})
  const [bulkResults, setBulkResults] = useState<BulkIssuanceItemResult[] | null>(null)

  const [type, setType] = useState<CredentialType>(prefillType ?? 'transcript')
  const [title, setTitle] = useState('')
  const [degree, setDegree] = useState('B.Tech Computer Science')
  const [graduationYear, setGraduationYear] = useState(String(new Date().getFullYear()))
  const [cgpa, setCgpa] = useState('8.7')
  const [document, setDocument] = useState<File | null>(null)
  const [documentConfirmed, setDocumentConfirmed] = useState(false)

  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getStudents()
      .then((list) => {
        setStudents(list)
        if (prefillStudentId) setStudentId(prefillStudentId)
        else if (list.length > 0) setStudentId((prev) => prev || list[0].id)
        else setStudentMode('manual')
      })
      .finally(() => setStudentsLoaded(true))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function handleManualLookup() {
    const identifier = manualIdentifier.trim()
    if (!identifier) return
    setManualLookupState('loading')
    setManualStudentName('')
    try {
      const student = await getStudentByIdentifier(identifier)
      setStudentId(student.id)
      setManualStudentName(student.name)
      setManualLookupState('found')
    } catch {
      setStudentId('')
      setManualLookupState('not-found')
    }
  }

  const filteredStudents = students.filter((s) => {
    const q = studentSearch.trim().toLowerCase()
    if (!q) return true
    return s.name.toLowerCase().includes(q) || s.identifier.toLowerCase().includes(q)
  })

  function toggleBulkStudent(id: string) {
    setBulkSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)

    if (!title.trim()) {
      setError(type === 'other' ? 'Enter a credential name.' : 'Enter a credential title.')
      return
    }

    if (!documentConfirmed) {
      setError('Please confirm that the attached document matches the credential details before issuing.')
      return
    }

    if (issueMode === 'bulk') {
      const selectedIds = Array.from(bulkSelected)
      if (selectedIds.length === 0) {
        setError('Select at least one student.')
        return
      }
      const missingDoc = selectedIds.find((id) => !bulkDocuments[id])
      if (missingDoc) {
        setError('Every selected student needs their own PDF document.')
        return
      }

      setSubmitting(true)
      setBulkResults(null)
      try {
        const results = await bulkIssueCredentials({
          studentIds: selectedIds,
          documents: selectedIds.map((id) => bulkDocuments[id] as File),
          type,
          title,
          degree: degree || undefined,
          graduationYear: graduationYear ? Number(graduationYear) : undefined,
          cgpa: (type === 'transcript' || type === 'degree') && cgpa ? Number(cgpa) : undefined,
        })
        setBulkResults(results)
      } catch (err) {
        if (err instanceof ApiError) setError(err.message)
        else setError('Something went wrong while issuing these credentials.')
      } finally {
        setSubmitting(false)
      }
      return
    }

    if (!studentId) {
      setError('Select a student.')
      return
    }
    if (!document) {
      setError('Upload a PDF document.')
      return
    }

    setSubmitting(true)
    try {
      await issueCredential({
        studentId,
        type,
        title,
        degree: degree || undefined,
        graduationYear: graduationYear ? Number(graduationYear) : undefined,
        cgpa: (type === 'transcript' || type === 'degree') && cgpa ? Number(cgpa) : undefined,
        document,
        fulfillsRequestId: fulfillsRequestId || undefined,
      })
      navigate('/institution/credentials/issued')
    } catch (err) {
      if (err instanceof ApiError) setError(err.message)
      else setError('Something went wrong while issuing this credential.')
    } finally {
      setSubmitting(false)
    }
  }

  // Purely presentational completion flags for the stepper below — do not gate submission or affect handleSubmit.
  const stepDone = {
    student: issueMode === 'bulk' ? bulkSelected.size > 0 : !!studentId,
    credential: !!title.trim(),
    details: !!degree.trim() && !!graduationYear,
    document: issueMode === 'bulk' ? Array.from(bulkSelected).every((id) => bulkDocuments[id]) && bulkSelected.size > 0 : !!document,
    issue: false,
  }

  return (
    <div>
      <PageHeader title="Issue Credential" eyebrow="Credential Issuance" icon={ShieldCheck} description="Sign a new credential into the student's CredChain wallet." />

      <div className="mb-6 flex max-w-2xl items-center justify-between">
        {STEPS.map((step, i) => {
          const done = stepDone[step.key]
          const isLast = i === STEPS.length - 1
          return (
            <div key={step.key} className="flex flex-1 items-center">
              <div className="flex flex-col items-center gap-1.5 text-center">
                <div
                  className={
                    done
                      ? 'flex h-9 w-9 items-center justify-center rounded-full border border-good-line bg-good-bg text-good shadow-glow-good'
                      : 'flex h-9 w-9 items-center justify-center rounded-full border border-line bg-surface text-faint'
                  }
                >
                  {done ? <Check className="h-4 w-4" strokeWidth={2.5} /> : <step.icon className="h-4 w-4" strokeWidth={2} />}
                </div>
                <span className={done ? 'text-[10px] font-bold uppercase tracking-wider text-good' : 'text-[10px] font-bold uppercase tracking-wider text-faint'}>
                  {step.label}
                </span>
              </div>
              {!isLast && <div className={done ? 'mx-2 h-px flex-1 bg-good-line' : 'mx-2 h-px flex-1 bg-line'} />}
            </div>
          )
        })}
      </div>

      <GlassPanel className="mb-6 max-w-2xl p-5">
        <div className="flex items-center gap-2.5">
          <IconTile icon={Lock} tone="good" size="sm" />
          <p className="text-sm font-bold text-ink">Credential Security</p>
        </div>
        <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-3">
          <span className="flex items-center gap-1.5 text-[12px] text-body">
            <Check className="h-3.5 w-3.5 shrink-0 text-good" strokeWidth={2.5} /> SHA-256 integrity
          </span>
          <span className="flex items-center gap-1.5 text-[12px] text-body">
            <Fingerprint className="h-3.5 w-3.5 shrink-0 text-good" strokeWidth={2} /> Ed25519 signature
          </span>
          <span className="flex items-center gap-1.5 text-[12px] text-body">
            <Check className="h-3.5 w-3.5 shrink-0 text-good" strokeWidth={2.5} /> Student-owned
          </span>
        </div>
      </GlassPanel>

      <Card className="max-w-2xl p-6">
        <div className="mb-4 flex gap-4 text-[13px]">
          <label className="flex items-center gap-1.5 text-ink">
            <input
              type="radio"
              checked={issueMode === 'single'}
              onChange={() => {
                setIssueMode('single')
                setBulkResults(null)
              }}
            />
            Single student
          </label>
          <label className="flex items-center gap-1.5 text-ink">
            <input
              type="radio"
              checked={issueMode === 'bulk'}
              onChange={() => {
                setIssueMode('bulk')
                setBulkResults(null)
              }}
            />
            Multiple students
          </label>
        </div>

        <form onSubmit={handleSubmit} className="space-y-6">
          <div>
            <SectionHeading>Student</SectionHeading>
          {issueMode === 'single' ? (
            <div>
              {studentsLoaded && (
                <div className="mb-2.5 flex gap-4 text-[13px]">
                  <label className="flex items-center gap-1.5 text-ink">
                    <input
                      type="radio"
                      checked={studentMode === 'select'}
                      onChange={() => setStudentMode('select')}
                      disabled={students.length === 0}
                    />
                    Select Existing Student
                  </label>
                  <label className="flex items-center gap-1.5 text-ink">
                    <input type="radio" checked={studentMode === 'manual'} onChange={() => setStudentMode('manual')} />
                    Enter Student Identifier
                  </label>
                </div>
              )}

              {studentMode === 'select' ? (
                students.length === 0 ? (
                  <p className="rounded-lg border border-dashed border-line bg-canvas-2/50 px-3.5 py-2.5 text-[13px] text-muted">
                    No students are currently linked to this institution.
                  </p>
                ) : (
                  <>
                    <div className="relative mb-2">
                      <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-faint" />
                      <Input
                        value={studentSearch}
                        onChange={(e) => setStudentSearch(e.target.value)}
                        placeholder="Search by name or student ID"
                        className="py-2 pl-8 pr-3 text-[13px]"
                      />
                    </div>
                    <Select
                      value={studentId}
                      onChange={(e) => setStudentId(e.target.value)}
                      size={Math.min(6, Math.max(3, filteredStudents.length))}
                      required
                    >
                      {filteredStudents.length === 0 && <option value="">No matching students</option>}
                      {filteredStudents.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.name} — {s.identifier}
                        </option>
                      ))}
                    </Select>
                  </>
                )
              ) : (
                <div className="flex gap-2">
                  <Input
                    value={manualIdentifier}
                    onChange={(e) => {
                      setManualIdentifier(e.target.value)
                      setManualLookupState('idle')
                      setStudentId('')
                    }}
                    placeholder="Student Identifier"
                  />
                  <Button
                    type="button"
                    variant="outline"
                    loading={manualLookupState === 'loading'}
                    onClick={handleManualLookup}
                  >
                    Look up
                  </Button>
                </div>
              )}

              {studentMode === 'manual' && manualLookupState === 'found' && (
                <p className="mt-1.5 text-[13px] text-good">Found: {manualStudentName}</p>
              )}
              {studentMode === 'manual' && manualLookupState === 'not-found' && (
                <p className="mt-1.5 text-[13px] text-bad">
                  Student not found. The student must create a CredChain account and be affiliated with your
                  institution before a credential can be issued.
                </p>
              )}
            </div>
          ) : (
            <div>
              {students.length === 0 ? (
                <p className="rounded-lg border border-dashed border-line bg-canvas-2/50 px-3.5 py-2.5 text-[13px] text-muted">
                  No students are currently linked to this institution.
                </p>
              ) : (
                <>
                  <div className="mb-2 flex items-center justify-between">
                    <div className="relative flex-1">
                      <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-faint" />
                      <Input
                        value={studentSearch}
                        onChange={(e) => setStudentSearch(e.target.value)}
                        placeholder="Search by name or student ID"
                        className="py-2 pl-8 pr-3 text-[13px]"
                      />
                    </div>
                    <div className="ml-2 flex shrink-0 gap-2">
                      <button
                        type="button"
                        onClick={() => setBulkSelected(new Set(filteredStudents.map((s) => s.id)))}
                        className="text-[12px] font-semibold text-primary hover:underline"
                      >
                        Select All
                      </button>
                      <button
                        type="button"
                        onClick={() => setBulkSelected(new Set())}
                        className="text-[12px] font-semibold text-muted hover:underline"
                      >
                        Clear All
                      </button>
                    </div>
                  </div>

                  <div className="max-h-72 space-y-1.5 overflow-y-auto rounded-lg border border-line p-2">
                    {filteredStudents.map((s) => (
                      <div key={s.id} className="rounded-md border border-line/60 p-2">
                        <label className="flex items-center gap-2 text-[13px] text-ink">
                          <input type="checkbox" checked={bulkSelected.has(s.id)} onChange={() => toggleBulkStudent(s.id)} />
                          <span className="flex-1">
                            {s.name} — {s.identifier}
                          </span>
                        </label>
                        {bulkSelected.has(s.id) && (
                          <input
                            type="file"
                            accept="application/pdf,.pdf"
                            onChange={(e) =>
                              setBulkDocuments((prev) => ({ ...prev, [s.id]: e.target.files?.[0] ?? null }))
                            }
                            className="mt-1.5 w-full rounded-md border border-line bg-surface px-2.5 py-1.5 text-xs text-ink outline-none file:mr-2 file:rounded file:border-0 file:bg-canvas-2 file:px-2 file:py-1 file:text-[11px] file:font-semibold file:text-ink"
                          />
                        )}
                      </div>
                    ))}
                  </div>
                  <p className="mt-1.5 text-[12px] text-muted">{bulkSelected.size} student(s) selected</p>
                </>
              )}
            </div>
          )}
          </div>

          <div className="border-t border-line pt-5">
            <SectionHeading>Credential Type</SectionHeading>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field label="Type">
                <Select value={type} onChange={(e) => setType(e.target.value as CredentialType)}>
                  {TYPE_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label={type === 'other' ? 'Credential Name' : 'Title'}>
                <Input
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder={type === 'other' ? 'e.g. Bonafide Certificate' : 'Enter credential title'}
                  required
                />
              </Field>
            </div>
          </div>

          <div className="border-t border-line pt-5">
            <SectionHeading>Academic Details</SectionHeading>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field label="Degree Program">
                <div className="relative">
                  <School className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-faint" strokeWidth={2} />
                  <Input value={degree} onChange={(e) => setDegree(e.target.value)} placeholder="e.g. B.Tech Computer Science" className="pl-9" />
                </div>
              </Field>
              <Field label="Grad Year">
                <div className="relative">
                  <CalendarDays className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-faint" strokeWidth={2} />
                  <Input type="number" min="1950" max="2100" value={graduationYear} onChange={(e) => setGraduationYear(e.target.value)} className="pl-9" />
                </div>
              </Field>
              {(type === 'transcript' || type === 'degree') && (
                <Field label="CGPA">
                  <div className="relative">
                    <BarChart3 className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-faint" strokeWidth={2} />
                    <Input type="number" step="0.1" min="0" max="10" value={cgpa} onChange={(e) => setCgpa(e.target.value)} required className="pl-9" />
                  </div>
                </Field>
              )}
            </div>
          </div>

          {issueMode === 'single' && (
            <div className="border-t border-line pt-5">
              <SectionHeading>Document</SectionHeading>
              <Field label="Source document (PDF)">
                <input
                  type="file"
                  accept="application/pdf,.pdf"
                  onChange={(e) => setDocument(e.target.files?.[0] ?? null)}
                  className="w-full rounded-lg border border-line bg-surface px-3.5 py-2.5 text-sm text-ink outline-none file:mr-3 file:rounded-md file:border-0 file:bg-canvas-2 file:px-3 file:py-1.5 file:text-xs file:font-semibold file:text-ink focus:border-primary"
                  required
                />
              </Field>
            </div>
          )}

          <div className="border-t border-line pt-5">
            <SectionHeading>Issuance</SectionHeading>
            <div className="mb-4 flex items-start gap-2.5 rounded-lg bg-primary-bg px-3.5 py-3">
              <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-primary" strokeWidth={2} />
              <p className="text-[12px] leading-relaxed text-ink">
                This credential will be cryptographically signed with your institution&rsquo;s private key before
                being added to the student&rsquo;s wallet.
              </p>
            </div>

            <label className="mb-4 flex items-start gap-2.5 text-[13px] text-ink">
              <input
                type="checkbox"
                checked={documentConfirmed}
                onChange={(e) => setDocumentConfirmed(e.target.checked)}
                required
                className="mt-0.5"
              />
              <span>I confirm that the attached document matches the student&rsquo;s credential details entered above.</span>
            </label>

            {error && <div className="mb-4 rounded-lg bg-bad-bg px-3.5 py-2.5 text-[13px] text-bad">{error}</div>}

            <Button type="submit" variant="solid" className="w-full" loading={submitting}>
              {submitting
                ? 'Signing with institution private key…'
                : issueMode === 'bulk'
                  ? `Sign & Issue ${bulkSelected.size || ''} Credential${bulkSelected.size === 1 ? '' : 's'}`
                  : 'Sign & Issue Credential'}
            </Button>
          </div>
        </form>

        {bulkResults && (
          <div className="mt-5 border-t border-line pt-4">
            <p className="mb-2 text-[13px] font-semibold text-ink">
              {bulkResults.length} credential{bulkResults.length === 1 ? '' : 's'} requested
            </p>
            <div className="space-y-1.5">
              {bulkResults.map((r) => (
                <div key={r.student_id} className="flex items-center justify-between gap-2 text-[13px]">
                  <span className="flex items-center gap-1.5">
                    {r.status === 'issued' ? (
                      <Check className="h-3.5 w-3.5 text-good" strokeWidth={2.5} />
                    ) : (
                      <X className="h-3.5 w-3.5 text-bad" strokeWidth={2.5} />
                    )}
                    {r.student_name ?? students.find((s) => s.id === r.student_id)?.name ?? r.student_id}
                  </span>
                  {r.status === 'issued' ? (
                    <Badge tone="good" size="sm">
                      Issued
                    </Badge>
                  ) : (
                    <span className="text-[12px] text-bad">Failed: {r.error}</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </Card>
    </div>
  )
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return <p className="mb-3 text-[11px] font-bold uppercase tracking-wider text-faint">{children}</p>
}
