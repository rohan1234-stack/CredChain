import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Plus, Inbox, ShieldCheck, FolderSearch, Send, Briefcase } from 'lucide-react'
import { getCompanyRequests, getCompanyShares } from '../../lib/api'
import { useAuth } from '../../context/AuthContext'
import type { BackendCredentialRequest, BackendShareGrant } from '../../types'
import { StatCard, Button, Badge, EmptyState, Card } from '../../components/ui'
import { SkeletonCard } from '../../components/ui/Skeleton'

/**
 * Reproduces the actual Stitch "company_dashboard" screen: greeting -> CTA row
 * (Create Job / View Applications) -> a large obsidian "network synced" hero
 * panel (violet/magenta glow, CSS particle-web instead of the fictional
 * illustration image) -> a 2x2 metric grid -> recent requests list. See
 * stitch2/company_dashboard/code.html + screen.png. Stitch's own screen shows
 * the fictional "Nexus Corp" and fake wallet-balance labels baked into its
 * network illustration ("12.45 ETH") — none of that appears below; every
 * name/number is the real `user.org_name` / real request+share counts already
 * fetched by this component.
 */
export function VerifierDashboard() {
  const { user } = useAuth()
  const [requests, setRequests] = useState<BackendCredentialRequest[]>([])
  const [shares, setShares] = useState<BackendShareGrant[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([getCompanyRequests(), getCompanyShares()])
      .then(([r, s]) => {
        setRequests(r)
        setShares(s)
      })
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="space-y-4"><SkeletonCard lines={3} /><SkeletonCard lines={3} /></div>

  const pending = requests.filter((r) => r.status === 'pending').length
  const activeShares = shares.filter((s) => s.status === 'active').length

  return (
    <div>
      {/* Greeting */}
      <div className="mb-4 flex flex-col gap-1">
        <h1 className="text-[28px] font-bold leading-tight tracking-tight text-ink font-[family-name:var(--font-display)]">
          Good {new Date().getHours() < 17 ? 'Afternoon' : 'Evening'},{' '}
          <span className="bg-gradient-to-br from-ai to-primary bg-clip-text text-transparent">{user?.org_name ?? 'Your Company'}</span>
        </h1>
        <p className="text-base text-muted">Verify talent with confidence.</p>
      </div>

      <div className="mb-6 flex flex-wrap gap-3">
        <Link to="/verifier/jobs">
          <Button variant="solid" icon={<Briefcase className="h-4 w-4" />}>
            Create Job
          </Button>
        </Link>
        <Link to="/verifier/applications">
          <Button variant="outline">View Applications</Button>
        </Link>
      </div>

      {/* Hero — Stitch's "Network Synced" illustrated panel, reproduced as CSS particle-web + glow */}
      <div
        className="relative mb-6 flex w-full items-center justify-center overflow-hidden rounded-xl border border-ai-line px-6 py-8"
        style={{ background: 'radial-gradient(ellipse at center, rgba(79,70,229,0.18) 0%, rgba(10,15,30,0.75) 70%)', backdropFilter: 'blur(20px)' }}
      >
        <div aria-hidden className="absolute -left-10 -top-10 h-48 w-48 rounded-full bg-ai/20 blur-[80px]" />
        <div aria-hidden className="absolute -bottom-10 -right-10 h-48 w-48 rounded-full bg-magenta/15 blur-[80px]" />
        <div aria-hidden className="absolute inset-0 bg-circuit-faint opacity-40" />
        <div className="relative flex flex-col items-center gap-2.5 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-full bg-ai/10 text-ai shadow-[0_0_24px_rgba(167,139,250,0.5)]">
            <ShieldCheck className="h-7 w-7" strokeWidth={2} />
          </div>
          <p className="text-xl font-semibold text-ink">Network Synced</p>
          <p className="rounded-full border border-ai-line bg-ai-bg px-3 py-1 font-[family-name:var(--font-mono)] text-[13px] text-ai">
            {activeShares} credentials shared with you
          </p>
        </div>
      </div>

      {/* Metrics — real request/share counts only; no fabricated job/application totals this component doesn't fetch */}
      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3">
        <StatCard value={requests.length} label="Requests Sent" icon={Send} />
        <StatCard value={pending} label="Pending" tone="warn" icon={FolderSearch} pulse={pending > 0} />
        <StatCard value={activeShares} label="Shared With You" tone="good" icon={ShieldCheck} />
      </div>

      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-[15px] font-bold text-ink">Recent Requests</h2>
        <Link to="/verifier/requests/new">
          <Button variant="solid" size="sm" icon={<Plus className="h-4 w-4" />}>
            Request Credentials
          </Button>
        </Link>
      </div>
      {requests.length === 0 ? (
        <EmptyState icon={Inbox} title="No requests yet" description="No requests yet." />
      ) : (
        <Card className="overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line bg-canvas-2/50 text-left text-[11px] font-bold uppercase tracking-wider text-faint">
                <th className="px-5 py-3">Student</th>
                <th className="px-5 py-3">Purpose</th>
                <th className="px-5 py-3">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {requests.slice(0, 8).map((r) => (
                <tr key={r.id}>
                  <td className="px-5 py-3 font-medium text-ink">{r.student_name}</td>
                  <td className="px-5 py-3 text-body">{r.purpose}</td>
                  <td className="px-5 py-3">
                    <Badge tone={r.status === 'approved' ? 'good' : r.status === 'declined' ? 'bad' : 'warn'} size="sm">
                      {r.status}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  )
}
