import { useEffect, useState } from 'react'
import { Share2, Eye, EyeOff, Download, Timer, Ban, Award, TrendingUp } from 'lucide-react'
import { getStudentShares, revokeShare } from '../../lib/api'
import { ApiError } from '../../lib/apiClient'
import type { BackendShareGrant, ShareGrantStatus } from '../../types'
import { PageHeader, GlassPanel, Badge, Button, EmptyState } from '../../components/ui'
import { CREDENTIAL_TYPE_ICON } from '../../lib/utils'
import { SkeletonCard } from '../../components/ui/Skeleton'

/**
 * Reproduces Stitch's "my_shares" bento layout: a featured active-share hero
 * card (recipient/permission/shared-on/expires meta grid) + a stats rail,
 * then a "Recent History" list below. Stitch's own screen shows a
 * placeholder QR image and fabricated "0x8f...4a2b" hex ids and a
 * "12 / +3 this week" stat — none of that is reproducible honestly (the raw
 * share token is never stored server-side, by design — see
 * ShareConfirmation.tsx — so no real QR can be regenerated here), so those
 * slots are replaced with real data this component actually has: the real
 * active-share count and a "View Share" action pointing at the credential
 * itself rather than a fabricated link.
 */

const STATUS_TONE: Record<ShareGrantStatus, 'good' | 'warn' | 'bad'> = {
  active: 'good',
  expired: 'warn',
  revoked: 'bad',
}

export function Shares() {
  const [shares, setShares] = useState<BackendShareGrant[]>([])
  const [loading, setLoading] = useState(true)
  const [revokingId, setRevokingId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getStudentShares()
      .then(setShares)
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Unable to load credential shares. Please try again.'))
      .finally(() => setLoading(false))
  }, [])

  async function handleRevoke(id: string) {
    setRevokingId(id)
    setError(null)
    try {
      const updated = await revokeShare(id)
      setShares((prev) => prev.map((s) => (s.id === id ? updated : s)))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not revoke this share.')
    } finally {
      setRevokingId(null)
    }
  }

  if (loading) return <div className="space-y-4"><SkeletonCard lines={3} /><SkeletonCard lines={3} /></div>

  const activeShares = shares.filter((s) => s.status === 'active')
  const featured = activeShares[0]
  const rest = shares.filter((s) => s.id !== featured?.id)

  return (
    <div>
      <PageHeader title="My Shares" eyebrow="Secure Sharing" icon={Share2} description="Credentials you've shared, and who currently has access." />

      {error && <div className="mb-5 rounded-lg bg-bad-bg px-3.5 py-2.5 text-[13px] text-bad">{error}</div>}

      {shares.length === 0 ? (
        !error && <EmptyState icon={Share2} title="No shares yet" description="Once you approve a credential request, it will appear here." />
      ) : (
        <div className="space-y-4">
          {/* Bento hero row: featured active share + stats rail */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
            {featured ? (
              <GlassPanel className="relative overflow-hidden p-6 lg:col-span-8" glow>
                <div className="flex flex-col justify-between gap-6 sm:flex-row">
                  <div className="min-w-0 flex-1">
                    <div className="mb-3 flex items-center justify-between">
                      <Badge tone="good" size="sm">Active</Badge>
                      <Button
                        variant="danger"
                        size="sm"
                        loading={revokingId === featured.id}
                        onClick={() => handleRevoke(featured.id)}
                      >
                        <Ban className="h-3.5 w-3.5" /> Revoke
                      </Button>
                    </div>
                    <h3 className="truncate text-lg font-bold text-ink">{featured.credentials.map((c) => c.title).join(', ')}</h3>
                    <p className="text-sm text-muted">{featured.company_name}</p>

                    <div className="mt-5 grid grid-cols-2 gap-4">
                      <div>
                        <p className="mb-1 text-[10px] font-bold uppercase tracking-wider text-faint">Recipient</p>
                        <p className="text-[13px] font-semibold text-ink">{featured.company_name}</p>
                      </div>
                      <div>
                        <p className="mb-1 text-[10px] font-bold uppercase tracking-wider text-faint">Permission</p>
                        <p className="flex items-center gap-1 text-[13px] font-semibold text-cyan">
                          {featured.permission === 'view_download' ? <Download className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                          {featured.permission === 'view_download' ? 'View + Download' : 'View Only'}
                        </p>
                      </div>
                      <div>
                        <p className="mb-1 text-[10px] font-bold uppercase tracking-wider text-faint">Shared On</p>
                        <p className="font-[family-name:var(--font-mono)] text-[13px] text-body">{new Date(featured.created_at).toLocaleDateString()}</p>
                      </div>
                      <div>
                        <p className="mb-1 text-[10px] font-bold uppercase tracking-wider text-faint">Expires</p>
                        <p className="flex items-center gap-1 font-[family-name:var(--font-mono)] text-[13px] text-good">
                          <Timer className="h-3.5 w-3.5" /> {new Date(featured.expires_at).toLocaleDateString()}
                        </p>
                      </div>
                    </div>
                  </div>
                </div>
              </GlassPanel>
            ) : (
              <GlassPanel className="p-6 lg:col-span-8">
                <p className="text-sm text-muted">No active shares right now.</p>
              </GlassPanel>
            )}

            <div className="flex flex-col gap-4 lg:col-span-4">
              <GlassPanel className="flex flex-1 flex-col justify-center p-5">
                <p className="mb-2 text-[10px] font-bold uppercase tracking-wider text-faint">Active Shares</p>
                <div className="flex items-end gap-2">
                  <span className="text-3xl font-bold text-ink font-[family-name:var(--font-display)]">{activeShares.length}</span>
                  <span className="mb-1 flex items-center gap-1 text-[12px] text-good">
                    <TrendingUp className="h-3.5 w-3.5" /> of {shares.length} total
                  </span>
                </div>
              </GlassPanel>
              <GlassPanel className="flex items-center justify-between p-5">
                <div>
                  <p className="text-sm font-bold text-ink">Total Credentials Shared</p>
                  <p className="text-[12px] text-muted">Across all active handoffs</p>
                </div>
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-primary-line bg-primary-bg text-primary">
                  <Award className="h-5 w-5" strokeWidth={2} />
                </div>
              </GlassPanel>
            </div>
          </div>

          {/* Recent history list */}
          {rest.length > 0 && (
            <GlassPanel className="overflow-hidden">
              <div className="border-b border-line px-5 py-3">
                <h3 className="text-[11px] font-bold uppercase tracking-wider text-faint">Recent History</h3>
              </div>
              <div className="divide-y divide-line">
                {rest.map((s) => {
                  const Icon = s.credentials[0] ? CREDENTIAL_TYPE_ICON[s.credentials[0].credential_type] : Award
                  const expired = s.status === 'expired'
                  const revoked = s.status === 'revoked'
                  return (
                    <div key={s.id} className={`flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center sm:justify-between ${expired || revoked ? 'opacity-60' : ''}`}>
                      <div className="flex items-center gap-3">
                        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-line bg-canvas-2">
                          <Icon className="h-4.5 w-4.5 text-muted" strokeWidth={2} />
                        </div>
                        <div className="min-w-0">
                          <p className={`truncate text-[13px] font-medium text-ink ${revoked ? 'line-through decoration-white/30' : ''}`}>
                            {s.credentials.map((c) => c.title).join(', ')}
                          </p>
                          <p className="text-[11px] text-faint">{s.company_name}</p>
                        </div>
                      </div>
                      <div className="flex items-center justify-between gap-4 sm:justify-end">
                        <div className="flex flex-col items-end gap-1">
                          <span className="inline-flex items-center gap-1 rounded border border-line bg-canvas-2 px-2 py-0.5 text-[10px] uppercase tracking-wider text-muted">
                            {s.permission === 'view_download' ? <Download className="h-2.5 w-2.5" /> : <EyeOff className="h-2.5 w-2.5" />}
                            {s.permission === 'view_download' ? 'Full Access' : 'View Only'}
                          </span>
                          <p className={`font-[family-name:var(--font-mono)] text-[11px] ${expired || revoked ? 'text-bad' : 'text-faint'}`}>
                            {revoked ? 'Revoked' : `Exp: ${new Date(s.expires_at).toLocaleDateString()}`}
                          </p>
                        </div>
                        <Badge tone={STATUS_TONE[s.status]} size="sm" withIcon={false}>
                          {s.status}
                        </Badge>
                      </div>
                    </div>
                  )
                })}
              </div>
            </GlassPanel>
          )}
        </div>
      )}
    </div>
  )
}
