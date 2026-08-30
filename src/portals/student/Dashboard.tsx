import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, Sparkles, Shield, Briefcase, FileStack, Share2, Inbox, Wallet } from 'lucide-react'
import { getCredentials, getActivity, getStudentRequests, getOpenJobs, getStudentShares, getMyJobApplications } from '../../lib/api'
import { useAuth } from '../../context/AuthContext'
import type { Credential, AccessLogEntry, Job } from '../../types'
import { Card, Button, StatCard, EmptyState, CheckRow, GlassPanel, Glow, CredentialCard3D } from '../../components/ui'
import { SkeletonGrid, SkeletonCard, SkeletonRow } from '../../components/ui/Skeleton'
import { CredentialCard } from './components/CredentialCard'
import { InstitutionLink } from './components/InstitutionLink'
import { timeBasedGreeting, ACTIVITY_ICON_MAP, TONE_CLASSES } from '../../lib/utils'

/** Splits "Good Morning, Rohan" into the period text and the real first name, so only the
 * name gets the Stitch gradient treatment (kept local to this page — no change to the shared
 * timeBasedGreeting helper, which other pages also rely on verbatim). */
function splitGreetingLocal(greeting: string): { period: string; name: string | null } {
  const idx = greeting.indexOf(', ')
  if (idx === -1) return { period: greeting, name: null }
  return { period: greeting.slice(0, idx), name: greeting.slice(idx + 2) }
}

function groupByDay(log: AccessLogEntry[]) {
  const today = log.filter((l) => l.timestamp.includes('AM') || l.timestamp.includes('PM') || l.timestamp === 'Just now')
  const rest = log.filter((l) => !today.includes(l))
  return { today, rest }
}

export function StudentDashboard() {
  const { user } = useAuth()
  const [credentials, setCredentials] = useState<Credential[]>([])
  const [activity, setActivity] = useState<AccessLogEntry[]>([])
  const [pendingRequests, setPendingRequests] = useState(0)
  const [openJobs, setOpenJobs] = useState<Job[]>([])
  const [applicationCount, setApplicationCount] = useState(0)
  const [shareCount, setShareCount] = useState(0)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      getCredentials().then(setCredentials),
      getActivity().then(setActivity),
      getStudentRequests().then((reqs) => setPendingRequests(reqs.filter((r) => r.status === 'pending').length)),
      getOpenJobs().then(setOpenJobs),
      getMyJobApplications().then((apps) => setApplicationCount(apps.length)),
      getStudentShares().then((shares) => setShareCount(shares.filter((s) => s.status === 'active').length)),
    ]).finally(() => setLoading(false))
  }, [])

  const total = credentials.length
  const { today, rest } = groupByDay(activity)
  const featuredJob = openJobs.find((j) => j.eligibility?.status === 'eligible') ?? openJobs[0]

  return (
    <div>
      <GlassPanel className="relative mb-6 grid grid-cols-1 items-center gap-6 overflow-hidden p-6 lg:grid-cols-[1.3fr_auto]">
        <Glow color="cyan" size={380} className="-left-16 -top-20" animate={false} />
        <Glow color="primary" size={320} className="-bottom-24 right-10" animate={false} />
        <div className="relative">
          {(() => {
            const { period, name } = splitGreetingLocal(timeBasedGreeting(user?.full_name))
            return (
              <div className="flex items-center gap-2">
                <h1 className="text-2xl font-bold tracking-tight text-ink font-[family-name:var(--font-display)]">
                  {period}
                  {name && (
                    <>
                      ,{' '}
                      <span className="bg-gradient-to-r from-primary to-cyan bg-clip-text text-transparent">{name}</span>
                    </>
                  )}
                </h1>
                <span className="text-2xl">👋</span>
              </div>
            )
          })()}
          <p className="mt-1 text-[15px] text-muted">Your academic credential passport.</p>
          <div className="mt-5 max-w-sm">
            <InstitutionLink />
          </div>
        </div>
        {!loading && credentials[0] && (
          <div className="relative hidden justify-self-end sm:flex">
            <CredentialCard3D issuer={credentials[0].issuer} title={credentials[0].title} subtitle="Latest credential" size="sm" />
          </div>
        )}
      </GlassPanel>

      {loading ? (
        <SkeletonGrid count={4} />
      ) : (
        <div className="mb-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
          <StatCard value={total} label="Credentials" icon={Wallet} />
          <StatCard value={pendingRequests} label="Incoming Requests" tone={pendingRequests > 0 ? 'warn' : 'neutral'} icon={Inbox} pulse={pendingRequests > 0} />
          <StatCard value={applicationCount} label="Applications" icon={FileStack} />
          <StatCard value={shareCount} label="Shared Credentials" icon={Share2} />
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-[15px] font-bold text-ink">Your Academic Credentials</h2>
            <Link to="/student/credentials" className="flex items-center gap-1 text-xs font-semibold text-primary hover:underline">
              View all <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>

          {loading ? (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              {[0, 1, 2].map((i) => (
                <SkeletonCard key={i} lines={2} />
              ))}
            </div>
          ) : total === 0 ? (
            <EmptyState
              icon={Wallet}
              title="No credentials yet"
              description="Once your university issues a credential, or you request one, it will appear here in your wallet."
            />
          ) : (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              {credentials.slice(0, 3).map((c) => (
                <CredentialCard key={c.id} credential={c} />
              ))}
            </div>
          )}

          <div className="mt-5">
            <div className="mb-3 flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-ai">
              <Sparkles className="h-3.5 w-3.5" strokeWidth={2.25} />
              AI Opportunity Insights
            </div>

            {loading ? (
              <SkeletonCard lines={3} />
            ) : featuredJob ? (
              <GlassPanel className="relative overflow-hidden border-ai-line p-5">
                <Glow color="ai" size={220} className="-right-10 -top-14" animate={false} />
                <div className="relative flex items-start justify-between gap-3">
                  <div>
                    <p className="text-[11px] font-semibold text-muted">{featuredJob.company_name}</p>
                    <h3 className="text-[15px] font-bold text-ink">{featuredJob.title}</h3>
                  </div>
                  {openJobs.length > 1 && (
                    <span className="shrink-0 rounded-full bg-surface-2 px-2.5 py-1 text-[11px] font-semibold text-muted">
                      +{openJobs.length - 1} more open
                    </span>
                  )}
                </div>

                {featuredJob.eligibility && (
                  <div className="relative mt-4 space-y-2 border-t border-ai-line pt-4">
                    {featuredJob.eligibility.checks.slice(0, 3).map((c) => (
                      <CheckRow
                        key={c.label}
                        label={c.label}
                        state={c.status === 'met' ? 'pass' : c.status === 'incomplete' ? 'gap' : 'fail'}
                        size="sm"
                      />
                    ))}
                  </div>
                )}

                <Link to={`/student/jobs/${featuredJob.id}`} className="relative">
                  <Button variant="solid" size="sm" className="mt-4" icon={<Sparkles className="h-3.5 w-3.5" />}>
                    View Eligibility &amp; Analyze with AI
                  </Button>
                </Link>
              </GlassPanel>
            ) : (
              <Card className="p-5">
                <div className="flex items-center gap-3">
                  <Briefcase className="h-5 w-5 shrink-0 text-faint" strokeWidth={2} />
                  <p className="text-[13px] text-muted">No open jobs from real companies right now — check back soon.</p>
                </div>
              </Card>
            )}
          </div>
        </div>

        <div>
          <h2 className="mb-3 text-[15px] font-bold text-ink">Recent Activity</h2>
          {loading ? (
            <div className="space-y-3">
              <SkeletonRow />
              <SkeletonRow />
            </div>
          ) : activity.length === 0 ? (
            <EmptyState icon={Shield} title="No activity yet" description="Actions on your credentials will show up here." />
          ) : (
            <Card className="p-4">
              {today.length > 0 && (
                <>
                  <div className="mb-2 text-[10px] font-bold uppercase tracking-wider text-faint">Today</div>
                  <div className="space-y-3">
                    {today.map((a) => (
                      <ActivityRow key={a.id} entry={a} />
                    ))}
                  </div>
                </>
              )}
              {rest.length > 0 && (
                <>
                  <div className="mb-2 mt-4 text-[10px] font-bold uppercase tracking-wider text-faint">Earlier</div>
                  <div className="space-y-3">
                    {rest.map((a) => (
                      <ActivityRow key={a.id} entry={a} />
                    ))}
                  </div>
                </>
              )}
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}

function ActivityRow({ entry }: { entry: AccessLogEntry }) {
  const { icon: Icon, tone } = ACTIVITY_ICON_MAP[entry.icon]
  return (
    <div className="flex items-start justify-between gap-2.5">
      <div className="flex items-start gap-2.5 min-w-0">
        <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${TONE_CLASSES[tone].text}`} strokeWidth={2} />
        <div className="min-w-0">
          <p className="truncate text-[13px] font-semibold text-ink">{entry.action}</p>
          <p className="text-[11px] text-faint">{entry.actor}</p>
        </div>
      </div>
      <span className="shrink-0 text-[11px] text-faint">{entry.timestamp}</span>
    </div>
  )
}
