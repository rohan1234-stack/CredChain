import { useEffect, useState } from 'react'
import { FileStack, ShieldCheck, ShieldQuestion, ListChecks, GraduationCap, Building2 } from 'lucide-react'
import { getCompanyApplications, updateApplicationStatus, verifyCredential } from '../../lib/api'
import { ApiError } from '../../lib/apiClient'
import type { CompanyJobApplication, ApplicationStatus, VerifyCredentialResponse } from '../../types'
import { PageHeader, Badge, Button, EmptyState, GlassPanel, Glow, WorkflowTimeline, buildJobApplicationSteps } from '../../components/ui'
import { Textarea } from '../../components/ui/Input'
import { InitialsAvatar } from '../../components/ui/IconTile'
import { SkeletonCard } from '../../components/ui/Skeleton'
import { useToast } from '../../components/ui/Toast'
import { CREDENTIAL_TYPE_ICON, cx } from '../../lib/utils'

const STATUS_TONE: Record<ApplicationStatus, 'good' | 'warn' | 'bad' | 'neutral' | 'primary'> = {
  applied: 'neutral',
  under_review: 'primary',
  shortlisted: 'primary',
  accepted: 'good',
  rejected: 'bad',
  withdrawn: 'neutral',
}

const STATUS_LABEL: Record<ApplicationStatus, string> = {
  applied: 'Applied',
  under_review: 'Under Review',
  shortlisted: 'Shortlisted',
  accepted: 'Accepted',
  rejected: 'Rejected',
  withdrawn: 'Withdrawn',
}

const NEXT_STEPS: Record<ApplicationStatus, { to: ApplicationStatus; label: string }[]> = {
  applied: [
    { to: 'under_review', label: 'Move to Under Review' },
    { to: 'rejected', label: 'Reject' },
  ],
  under_review: [
    { to: 'shortlisted', label: 'Shortlist' },
    { to: 'rejected', label: 'Reject' },
  ],
  shortlisted: [
    { to: 'accepted', label: 'Accept' },
    { to: 'rejected', label: 'Reject' },
  ],
  accepted: [],
  rejected: [],
  withdrawn: [],
}

/** Eligibility check tone -> the Stitch "Deterministic Eligibility" card accent (a thin
 * bottom bar + a tinted check-circle chip, not just a checkmark row). */
const CHECK_TONE = {
  pass: { bar: 'bg-good', chip: 'bg-good-bg text-good' },
  gap: { bar: 'bg-warn', chip: 'bg-warn-bg text-warn' },
  fail: { bar: 'bg-bad', chip: 'bg-bad-bg text-bad' },
} as const

function initialsOf(name: string): string {
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

export function Applications() {
  const toast = useToast()
  const [applications, setApplications] = useState<CompanyJobApplication[]>([])
  const [loading, setLoading] = useState(true)
  const [verifying, setVerifying] = useState<string | null>(null)
  const [verifyResults, setVerifyResults] = useState<Record<string, VerifyCredentialResponse>>({})
  const [updating, setUpdating] = useState<string | null>(null)
  const [rejectingId, setRejectingId] = useState<string | null>(null)
  const [rejectReason, setRejectReason] = useState('')
  const [error, setError] = useState<string | null>(null)

  function refresh() {
    return getCompanyApplications().then(setApplications)
  }

  useEffect(() => {
    refresh()
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Unable to load applications. Please try again.'))
      .finally(() => setLoading(false))
  }, [])

  async function handleVerify(credentialId: string) {
    setVerifying(credentialId)
    try {
      const result = await verifyCredential(credentialId)
      setVerifyResults((prev) => ({ ...prev, [credentialId]: result }))
    } catch {
      // surfaced inline via absence of a result row
    } finally {
      setVerifying(null)
    }
  }

  async function handleStatus(applicationId: string, status: ApplicationStatus, reason?: string) {
    setUpdating(applicationId)
    setError(null)
    try {
      await updateApplicationStatus(applicationId, status, reason)
      setRejectingId(null)
      setRejectReason('')
      await refresh()
      toast(status === 'rejected' ? 'Application rejected' : `Moved to ${STATUS_LABEL[status]}`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not update this application.')
    } finally {
      setUpdating(null)
    }
  }

  if (loading) {
    return (
      <div>
        <PageHeader title="Applications" eyebrow="Application Pipeline" icon={FileStack} description="Students who applied to your jobs. You never see students who haven't applied." />
        <div className="space-y-4">
          <SkeletonCard lines={4} />
          <SkeletonCard lines={4} />
        </div>
      </div>
    )
  }

  return (
    <div>
      <PageHeader title="Applications" eyebrow="Application Pipeline" icon={FileStack} description="Students who applied to your jobs. You never see students who haven't applied." />

      {error && <div className="mb-5 max-w-5xl rounded-lg bg-bad-bg px-3.5 py-2.5 text-[13px] text-bad">{error}</div>}

      {applications.length === 0 ? (
        !error && <EmptyState icon={FileStack} title="No applications yet" description="Applications to your published jobs will appear here." />
      ) : (
        <div className="max-w-5xl space-y-8">
          {applications.map((a) => {
            const availableCount = a.credential_request
              ? a.credential_request.requested_credentials.filter((label) =>
                  a.credential_request!.shared_credentials.some((s) => s.title.toLowerCase().includes(label.toLowerCase()))
                ).length
              : 0
            const totalRequired = a.credential_request?.requested_credentials.length ?? 0

            return (
              <div key={a.id} className="flex flex-col gap-6">
                {/* Candidate summary — Stitch "review console" header: glowing avatar ring, name, role line, status pill */}
                <GlassPanel className="relative flex flex-col items-start gap-6 overflow-hidden p-6 md:flex-row md:items-center md:justify-between">
                  <Glow color="primary" size={260} className="-right-16 -top-20" animate={false} />
                  <div className="relative flex items-center gap-6">
                    <div className="relative rounded-full border-2 border-primary-line p-0.5 shadow-glow-primary">
                      <InitialsAvatar initials={initialsOf(a.student_name)} tone="primary" size="md" />
                    </div>
                    <div>
                      <h2 className="text-xl font-bold tracking-tight text-ink font-[family-name:var(--font-display)]">{a.student_name}</h2>
                      <p className="mt-1 flex items-center gap-1.5 text-[13px] text-cyan">
                        <Building2 className="h-3.5 w-3.5" strokeWidth={2} />
                        {a.job_title}
                      </p>
                      <p className="mt-0.5 text-[11px] text-faint font-[family-name:var(--font-mono)]">
                        {a.student_identifier} · Applied {new Date(a.created_at).toLocaleDateString()}
                      </p>
                    </div>
                  </div>
                  <div className="relative flex flex-col items-start gap-2 border-t border-line pt-4 md:items-end md:border-t-0 md:pt-0">
                    <Badge tone={STATUS_TONE[a.status]} withIcon={false}>
                      {STATUS_LABEL[a.status].toUpperCase()}
                    </Badge>
                  </div>
                </GlassPanel>

                <GlassPanel className="-mt-4 p-5">
                  <WorkflowTimeline steps={buildJobApplicationSteps(a.history, a.status, a.rejection_reason)} />
                </GlassPanel>

                <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
                  {/* Left column — Deterministic Eligibility + Shared Credentials (Stitch cols 1-8) */}
                  <div className="flex flex-col gap-6 lg:col-span-8">
                    <GlassPanel className="relative overflow-hidden p-6">
                      <Glow color="primary" size={200} className="-right-10 -top-10" animate={false} />
                      <div className="relative mb-5 flex items-center justify-between gap-2 border-b border-line pb-4">
                        <h3 className="flex items-center gap-2 text-base font-semibold text-ink">
                          <ListChecks className="h-5 w-5 text-primary" strokeWidth={2} />
                          Deterministic Eligibility
                        </h3>
                        <Badge
                          tone={a.eligibility.status === 'eligible' ? 'good' : a.eligibility.status === 'incomplete' ? 'warn' : 'bad'}
                          size="sm"
                          withIcon={false}
                        >
                          {a.eligibility.status === 'eligible' ? 'Eligible' : a.eligibility.status === 'incomplete' ? 'Incomplete' : 'Not Eligible'}
                        </Badge>
                      </div>
                      <div className="relative grid grid-cols-1 gap-4 sm:grid-cols-3">
                        {a.eligibility.checks.map((c) => {
                          const state = c.status === 'met' ? 'pass' : c.status === 'incomplete' ? 'gap' : 'fail'
                          const tone = CHECK_TONE[state]
                          return (
                            <div key={c.label} className="rounded-lg border border-line bg-canvas-2/60 p-4 transition-colors hover:border-cyan/30">
                              <div className="mb-2 flex items-start justify-between gap-2">
                                <span className="font-[family-name:var(--font-mono)] text-[11px] uppercase tracking-wider text-faint">{c.label}</span>
                                <span className={cx('flex h-5 w-5 shrink-0 items-center justify-center rounded-full', tone.chip)}>
                                  {state === 'pass' ? <ShieldCheck className="h-3 w-3" strokeWidth={2.5} /> : <ShieldQuestion className="h-3 w-3" strokeWidth={2.5} />}
                                </span>
                              </div>
                              <p className="text-sm text-ink">{state === 'gap' ? 'No data on file' : state === 'pass' ? 'Requirement met' : 'Requirement not met'}</p>
                              <div className="mt-3 h-1 overflow-hidden rounded-full bg-canvas-2">
                                <div className={cx('h-full', tone.bar, state === 'pass' ? 'w-full' : state === 'gap' ? 'w-1/2' : 'w-1/4')} />
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    </GlassPanel>

                    <GlassPanel className="p-6">
                      <div className="mb-5 flex items-center justify-between border-b border-line pb-4">
                        <h3 className="flex items-center gap-2 text-base font-semibold text-ink">
                          <GraduationCap className="h-5 w-5 text-cyan" strokeWidth={2} />
                          Shared Credentials
                        </h3>
                        {a.credential_request && (
                          <span className="rounded-full bg-surface-2 px-3 py-1 font-[family-name:var(--font-mono)] text-[11px] text-faint">
                            {a.credential_request.shared_credentials.length} Credential{a.credential_request.shared_credentials.length === 1 ? '' : 's'}
                          </span>
                        )}
                      </div>

                      {!a.credential_request ? (
                        <p className="text-[13px] text-muted">This job has no required documents on file.</p>
                      ) : a.credential_request.shared_credentials.length === 0 ? (
                        <p className="text-[13px] font-semibold text-warn">Not shared</p>
                      ) : (
                        <div className="space-y-3">
                          {a.credential_request.shared_credentials.map((s) => {
                            const Icon = CREDENTIAL_TYPE_ICON[s.credential_type]
                            const vr = verifyResults[s.id]
                            const matchesRequested = a.credential_request!.requested_credentials.some((label) =>
                              s.title.toLowerCase().includes(label.toLowerCase())
                            )
                            return (
                              <div
                                key={s.id}
                                className="group relative overflow-hidden rounded-lg border border-line bg-gradient-to-br from-canvas-2 to-surface p-5"
                              >
                                <div className="pointer-events-none absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/5 to-transparent transition-transform duration-1000 ease-in-out group-hover:translate-x-full" />
                                <div className="relative flex flex-col gap-4 sm:flex-row">
                                  <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-lg border border-line bg-surface-2">
                                    <Icon className="h-6 w-6 text-faint" strokeWidth={1.75} />
                                  </div>
                                  <div className="flex-1">
                                    <div className="flex items-start justify-between gap-3">
                                      <div>
                                        <p className="font-semibold text-ink">{s.title}</p>
                                        {!matchesRequested && (
                                          <p className="mt-0.5 text-[11px] font-semibold text-warn">Does not match requested type</p>
                                        )}
                                      </div>
                                      <div className="shrink-0">
                                        {vr ? (
                                          <Badge tone={vr.result === 'VERIFIED' ? 'good' : 'bad'} size="sm" withIcon={false}>
                                            {vr.result === 'TYPE_MISMATCH' ? 'Credential Type Mismatch' : vr.result}
                                          </Badge>
                                        ) : (
                                          <Button
                                            variant="outline"
                                            size="sm"
                                            loading={verifying === s.id}
                                            icon={<ShieldCheck className="h-3.5 w-3.5" />}
                                            onClick={() => handleVerify(s.id)}
                                          >
                                            Verify
                                          </Button>
                                        )}
                                      </div>
                                    </div>
                                  </div>
                                </div>
                              </div>
                            )
                          })}
                        </div>
                      )}
                    </GlassPanel>
                  </div>

                  {/* Right column — Required Documents + Pipeline Actions (Stitch cols 9-12, the "aside" treatment) */}
                  <div className="lg:col-span-4">
                    <GlassPanel className="flex h-full flex-col gap-6 p-6">
                      <div>
                        <h3 className="mb-4 flex items-center gap-2 border-b border-line pb-4 text-base font-semibold text-ink">
                          <FileStack className="h-5 w-5 text-primary" strokeWidth={2} />
                          Required Documents
                        </h3>
                        {a.credential_request ? (
                          <>
                            <div className="mb-3 flex items-center justify-between">
                              <span className="font-[family-name:var(--font-mono)] text-[11px] text-faint">COMPLETENESS</span>
                              <Badge tone={availableCount === totalRequired ? 'good' : 'warn'} size="sm" withIcon={false}>
                                {availableCount} / {totalRequired}
                              </Badge>
                            </div>
                            <div className="flex flex-wrap gap-1.5">
                              {a.credential_request.requested_credentials.map((label) => {
                                const has = a.credential_request!.shared_credentials.some((s) => s.title.toLowerCase().includes(label.toLowerCase()))
                                return (
                                  <span
                                    key={label}
                                    className={cx(
                                      'rounded-full border px-2.5 py-1 text-[11px] font-medium',
                                      has ? 'border-good-line bg-good-bg text-good' : 'border-line bg-canvas-2 text-muted'
                                    )}
                                  >
                                    {label}
                                  </span>
                                )
                              })}
                            </div>
                          </>
                        ) : (
                          <p className="text-[13px] text-muted">No required documents on file.</p>
                        )}
                      </div>

                      {NEXT_STEPS[a.status].length > 0 && (
                        <div className="mt-auto border-t border-line pt-5">
                          {rejectingId === a.id ? (
                            <div className="space-y-2">
                              <Textarea
                                value={rejectReason}
                                onChange={(e) => setRejectReason(e.target.value)}
                                placeholder='Reason the student will see, e.g. "Required Migration Certificate was not submitted."'
                                rows={2}
                              />
                              <div className="flex gap-2">
                                <Button variant="outline" size="sm" onClick={() => { setRejectingId(null); setRejectReason('') }}>
                                  Cancel
                                </Button>
                                <Button
                                  variant="solid"
                                  size="sm"
                                  loading={updating === a.id}
                                  disabled={!rejectReason.trim()}
                                  onClick={() => handleStatus(a.id, 'rejected', rejectReason)}
                                >
                                  Confirm Reject
                                </Button>
                              </div>
                            </div>
                          ) : (
                            <div className="flex flex-col gap-2">
                              {NEXT_STEPS[a.status].map((step) =>
                                step.to === 'rejected' ? (
                                  <Button key={step.to} variant="outline" size="sm" onClick={() => setRejectingId(a.id)}>
                                    {step.label}
                                  </Button>
                                ) : (
                                  <Button
                                    key={step.to}
                                    variant="solid"
                                    size="sm"
                                    loading={updating === a.id}
                                    onClick={() => handleStatus(a.id, step.to)}
                                  >
                                    {step.label}
                                  </Button>
                                )
                              )}
                            </div>
                          )}
                        </div>
                      )}
                    </GlassPanel>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
