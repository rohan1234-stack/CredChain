import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Briefcase, Plus, X, Pencil, MapPin, Clock3, CalendarClock, GraduationCap, ShieldAlert } from 'lucide-react'
import { getMyJobs, createJob, updateJob, publishJob, closeJob } from '../../lib/api'
import { ApiError } from '../../lib/apiClient'
import { useAuth } from '../../context/AuthContext'
import type { Job, JobEmploymentType, JobStatus } from '../../types'
import { PageHeader, Card, Button, Badge, EmptyState, Field } from '../../components/ui'
import { Input, Select, Textarea } from '../../components/ui/Input'
import { SkeletonCard } from '../../components/ui/Skeleton'

const EMPLOYMENT_LABEL: Record<JobEmploymentType, string> = {
  full_time: 'Full-time',
  part_time: 'Part-time',
  internship: 'Internship',
  contract: 'Contract',
}

/** DRAFT reads neutral (not yet live), OPEN reads good (actively accepting applicants),
 * CLOSED reads neutral-muted — a closed job isn't a failure state, so it must not read
 * as alarming red. */
const STATUS_TONE: Record<JobStatus, 'good' | 'warn' | 'bad' | 'neutral' | 'primary'> = {
  draft: 'neutral',
  open: 'good',
  closed: 'neutral',
}

const EMPLOYMENT_OPTIONS: { value: JobEmploymentType; label: string }[] = [
  { value: 'full_time', label: 'Full-time' },
  { value: 'part_time', label: 'Part-time' },
  { value: 'internship', label: 'Internship' },
  { value: 'contract', label: 'Contract' },
]

function csv(s: string): string[] {
  return s
    .split(',')
    .map((x) => x.trim())
    .filter(Boolean)
}

export function Jobs() {
  const { user } = useAuth()
  const isVerified = user?.company_verification_status === 'verified'
  const [jobs, setJobs] = useState<Job[]>([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [location, setLocation] = useState('')
  const [employmentType, setEmploymentType] = useState<JobEmploymentType>('full_time')
  const [requiredDegree, setRequiredDegree] = useState('')
  const [minimumCgpa, setMinimumCgpa] = useState('')
  const [gradYear, setGradYear] = useState('')
  const [skills, setSkills] = useState('')
  const [certifications, setCertifications] = useState('')
  const [documents, setDocuments] = useState('')

  function refresh() {
    return getMyJobs().then(setJobs)
  }

  useEffect(() => {
    refresh()
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Unable to load jobs. Please try again.'))
      .finally(() => setLoading(false))
  }, [])

  function resetForm() {
    setTitle('')
    setDescription('')
    setLocation('')
    setEmploymentType('full_time')
    setRequiredDegree('')
    setMinimumCgpa('')
    setGradYear('')
    setSkills('')
    setCertifications('')
    setDocuments('')
  }

  function openCreateForm() {
    resetForm()
    setEditingId(null)
    setError(null)
    setShowForm(true)
  }

  function openEditForm(job: Job) {
    setTitle(job.title)
    setDescription(job.description)
    setLocation(job.location ?? '')
    setEmploymentType(job.employment_type)
    setRequiredDegree(job.required_degree ?? '')
    setMinimumCgpa(job.minimum_cgpa != null ? String(job.minimum_cgpa) : '')
    setGradYear(job.graduation_year_requirement != null ? String(job.graduation_year_requirement) : '')
    setSkills(job.required_skills.join(', '))
    setCertifications(job.required_certifications.join(', '))
    setDocuments(job.required_documents.join(', '))
    setEditingId(job.id)
    setError(null)
    setShowForm(true)
  }

  function closeForm() {
    setShowForm(false)
    setEditingId(null)
    resetForm()
  }

  async function handleSave() {
    if (!title.trim() || !description.trim()) return
    setSaving(true)
    setError(null)
    const payload = {
      title,
      description,
      location: location || undefined,
      employment_type: employmentType,
      required_degree: requiredDegree || undefined,
      minimum_cgpa: minimumCgpa ? Number(minimumCgpa) : undefined,
      graduation_year_requirement: gradYear ? Number(gradYear) : undefined,
      required_skills: csv(skills),
      required_certifications: csv(certifications),
      required_documents: csv(documents),
    }
    try {
      if (editingId) {
        await updateJob(editingId, payload)
      } else {
        await createJob(payload)
      }
      closeForm()
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save this job.')
    } finally {
      setSaving(false)
    }
  }

  async function handlePublish(id: string) {
    await publishJob(id)
    await refresh()
  }

  async function handleClose(id: string) {
    await closeJob(id)
    await refresh()
  }

  if (loading) {
    return (
      <div>
        <PageHeader title="Jobs" eyebrow="Job Postings" icon={Briefcase} description=" " />
        <SkeletonCard lines={3} />
      </div>
    )
  }

  return (
    <div>
      <PageHeader
        title="Jobs"
        eyebrow="Job Postings"
        icon={Briefcase}
        description="Postings you've created for this company."
        action={
          <Button variant="solid" icon={showForm ? <X className="h-3.5 w-3.5" /> : <Plus className="h-3.5 w-3.5" />} onClick={() => (showForm ? closeForm() : openCreateForm())}>
            {showForm ? 'Cancel' : 'New Job'}
          </Button>
        }
      />

      {error && !showForm && <div className="mb-5 rounded-lg bg-bad-bg px-3.5 py-2.5 text-[13px] text-bad">{error}</div>}

      {user?.company_verification_status === 'pending' && (
        <div className="mb-5 flex items-start gap-3 rounded-xl border border-warn-line bg-warn-bg px-4 py-3.5 text-warn">
          <Clock3 className="mt-0.5 h-5 w-5 shrink-0" strokeWidth={2} />
          <div>
            <p className="text-sm font-semibold">Pending verification</p>
            <p className="text-[13px] leading-relaxed">
              Your company account is awaiting review by a CredChain administrator. You can create and edit draft jobs, but publishing is disabled
              until your account is approved.
            </p>
          </div>
        </div>
      )}
      {user?.company_verification_status === 'rejected' && (
        <div className="mb-5 flex items-start gap-3 rounded-xl border border-bad-line bg-bad-bg px-4 py-3.5 text-bad">
          <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0" strokeWidth={2} />
          <div>
            <p className="text-sm font-semibold">Verification rejected</p>
            <p className="text-[13px] leading-relaxed">
              {user.company_rejection_reason || 'Your company account was not approved.'} Jobs cannot be published.
            </p>
          </div>
        </div>
      )}

      {showForm && (
        <Card className="mb-6 p-6">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Title">
              <Input value={title} onChange={(e) => setTitle(e.target.value)} />
            </Field>
            <Field label="Location">
              <Input value={location} onChange={(e) => setLocation(e.target.value)} placeholder="e.g. Bengaluru, India" />
            </Field>
            <Field label="Employment Type">
              <Select value={employmentType} onChange={(e) => setEmploymentType(e.target.value as JobEmploymentType)}>
                {EMPLOYMENT_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Required Degree">
              <Input value={requiredDegree} onChange={(e) => setRequiredDegree(e.target.value)} placeholder="e.g. B.Tech Computer Science" />
            </Field>
            <Field label="Minimum CGPA">
              <Input value={minimumCgpa} onChange={(e) => setMinimumCgpa(e.target.value)} placeholder="e.g. 7.5" />
            </Field>
            <Field label="Graduation Year">
              <Input value={gradYear} onChange={(e) => setGradYear(e.target.value)} placeholder="e.g. 2026" />
            </Field>
          </div>

          <div className="mt-4">
            <Field label="Description">
              <Textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={4} />
            </Field>
          </div>

          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
            <Field label="Required Skills (comma-separated)">
              <Input value={skills} onChange={(e) => setSkills(e.target.value)} />
            </Field>
            <Field label="Required Certifications (comma-separated)">
              <Input value={certifications} onChange={(e) => setCertifications(e.target.value)} />
            </Field>
            <Field label="Required Documents (comma-separated)">
              <Input value={documents} onChange={(e) => setDocuments(e.target.value)} placeholder="e.g. Transcript, Degree" />
            </Field>
          </div>

          {error && <div className="mt-4 rounded-lg bg-bad-bg px-3.5 py-2.5 text-[13px] text-bad">{error}</div>}

          <Button variant="solid" className="mt-5" loading={saving} disabled={!title.trim() || !description.trim()} onClick={handleSave}>
            {editingId ? 'Save Changes' : 'Save as Draft'}
          </Button>
        </Card>
      )}

      {jobs.length === 0 && !showForm ? (
        !error && <EmptyState icon={Briefcase} title="No jobs yet" description="Create a job posting to get started." />
      ) : (
        <div className="space-y-4">
          {jobs.map((j) => (
            <Card key={j.id} className="p-5">
              {/* Top row — status pill + short id chip, matching Stitch's "OPEN · ID: 0x8a92...f4e1" row */}
              <div className="mb-3 flex items-center justify-between gap-2">
                <Badge tone={STATUS_TONE[j.status]} withIcon={false} size="sm">
                  {j.status.toUpperCase()}
                </Badge>
                <span className="font-[family-name:var(--font-mono)] text-[11px] text-faint">ID: {j.id.slice(0, 8)}…</span>
              </div>

              <p className="text-lg font-bold text-ink font-[family-name:var(--font-display)]">{j.title}</p>

              <div className="mt-4 grid grid-cols-2 gap-4">
                <div>
                  <p className="flex items-center gap-1 font-[family-name:var(--font-mono)] text-[10px] uppercase tracking-wider text-faint">
                    <MapPin className="h-3 w-3" /> Location
                  </p>
                  <p className="mt-0.5 text-sm text-ink">{j.location || 'Not specified'}</p>
                </div>
                <div>
                  <p className="flex items-center gap-1 font-[family-name:var(--font-mono)] text-[10px] uppercase tracking-wider text-faint">
                    <Clock3 className="h-3 w-3" /> Type
                  </p>
                  <p className="mt-0.5 text-sm text-ink">{EMPLOYMENT_LABEL[j.employment_type]}</p>
                </div>
                <div>
                  <p className="flex items-center gap-1 font-[family-name:var(--font-mono)] text-[10px] uppercase tracking-wider text-faint">
                    <CalendarClock className="h-3 w-3" /> Deadline
                  </p>
                  <p className="mt-0.5 text-sm text-ink">
                    {j.application_deadline ? new Date(j.application_deadline).toLocaleDateString() : 'Not set'}
                  </p>
                </div>
                <div>
                  <p className="flex items-center gap-1 font-[family-name:var(--font-mono)] text-[10px] uppercase tracking-wider text-faint">
                    <GraduationCap className="h-3 w-3" /> Required Degree
                  </p>
                  <p className="mt-0.5 text-sm text-ink">{j.required_degree || 'Not specified'}</p>
                </div>
              </div>

              {j.description && (
                <div className="mt-4 rounded-lg border border-line bg-canvas-2/60 p-4">
                  <p className="font-[family-name:var(--font-mono)] text-[10px] uppercase tracking-wider text-faint">Eligibility</p>
                  <p className="mt-1 line-clamp-2 text-[13px] leading-relaxed text-body">{j.description}</p>
                </div>
              )}

              <div className="mt-4 flex flex-wrap items-center justify-end gap-2 border-t border-line pt-4">
                {j.status !== 'closed' && (
                  <Button variant="outline" size="sm" icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => openEditForm(j)}>
                    Edit
                  </Button>
                )}
                {j.status === 'draft' && (
                  <Button variant="solid" size="sm" disabled={!isVerified} title={isVerified ? undefined : 'Your company account must be verified before publishing jobs'} onClick={() => handlePublish(j.id)}>
                    Publish
                  </Button>
                )}
                {j.status === 'open' && (
                  <>
                    <Button variant="outline" size="sm" onClick={() => handleClose(j.id)}>
                      Close
                    </Button>
                    <Link to="/verifier/applications">
                      <Button variant="solid" size="sm">
                        View Applications
                      </Button>
                    </Link>
                  </>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
