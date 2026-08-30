import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { FileStack, Clock3, RefreshCw, Star, CheckCircle2, XCircle, Ban } from 'lucide-react'
import { getMyJobApplications, withdrawApplication } from '../../lib/api'
import { ApiError } from '../../lib/apiClient'
import type { StudentJobApplication, ApplicationStatus } from '../../types'
import { PageHeader, Badge, Button, EmptyState, GlassPanel, WorkflowTimeline, buildJobApplicationSteps } from '../../components/ui'
import { SkeletonCard } from '../../components/ui/Skeleton'

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

const STATUS_ICON: Record<ApplicationStatus, typeof Clock3> = {
  applied: Clock3,
  under_review: RefreshCw,
  shortlisted: Star,
  accepted: CheckCircle2,
  rejected: XCircle,
  withdrawn: Ban,
}

const WITHDRAWABLE: ApplicationStatus[] = ['applied', 'under_review', 'shortlisted']

export function MyApplications() {
  const [applications, setApplications] = useState<StudentJobApplication[]>([])
  const [loading, setLoading] = useState(true)
  const [withdrawingId, setWithdrawingId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  function load() {
    return getMyJobApplications()
      .then(setApplications)
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Unable to load your applications. Please try again.'))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
  }, [])

  async function handleWithdraw(id: string) {
    setWithdrawingId(id)
    setError(null)
    try {
      await withdrawApplication(id)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not withdraw this application.')
    } finally {
      setWithdrawingId(null)
    }
  }

  if (loading) return <div className="space-y-4"><SkeletonCard lines={3} /><SkeletonCard lines={3} /></div>

  return (
    <div>
      <PageHeader title="My Applications" eyebrow="Application Pipeline" icon={FileStack} description="Real applications you've submitted to real companies." />

      {error && <div className="mb-5 max-w-2xl rounded-lg bg-bad-bg px-3.5 py-2.5 text-[13px] text-bad">{error}</div>}

      {applications.length === 0 ? (
        !error && <EmptyState icon={FileStack} title="No applications yet" description="Apply to a job to see it tracked here." />
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {applications.map((a) => {
            const StatusIcon = STATUS_ICON[a.status]
            const tone = STATUS_TONE[a.status]
            return (
              <GlassPanel
                key={a.id}
                className={`relative overflow-hidden p-5 ${a.status === 'rejected' ? 'border-l-[3px] border-l-bad' : ''}`}
              >
                <Link to={`/student/jobs/${a.job_id}`} className="block">
                  <div className="mb-3 flex items-start justify-between">
                    <Badge tone={tone} size="sm">
                      {STATUS_LABEL[a.status]}
                    </Badge>
                    <StatusIcon className={`h-5 w-5 ${tone === 'good' ? 'text-good' : tone === 'bad' ? 'text-bad' : tone === 'primary' ? 'text-primary' : 'text-faint'}`} strokeWidth={2} />
                  </div>
                  <h3 className="text-[15px] font-bold text-ink hover:underline">{a.job_title}</h3>
                  <p className="mb-4 text-xs text-muted">{a.company_name}</p>
                </Link>

                <div className="rounded-lg border border-white/5 bg-canvas-2/40 px-3.5 py-3">
                  <WorkflowTimeline steps={buildJobApplicationSteps(a.history, a.status, a.rejection_reason)} />
                </div>

                {WITHDRAWABLE.includes(a.status) && (
                  <div className="mt-3 border-t border-white/5 pt-3">
                    <Button variant="outline" size="sm" loading={withdrawingId === a.id} onClick={() => handleWithdraw(a.id)}>
                      Withdraw Application
                    </Button>
                  </div>
                )}
              </GlassPanel>
            )
          })}
        </div>
      )}
    </div>
  )
}
