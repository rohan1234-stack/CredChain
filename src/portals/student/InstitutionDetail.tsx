import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Landmark, MapPin, Globe, GraduationCap, ShieldCheck, Info } from 'lucide-react'
import { getInstitution } from '../../lib/api'
import { ApiError } from '../../lib/apiClient'
import type { InstitutionSummary } from '../../types'
import { EmptyState, GlassPanel, Glow, IconTile, Badge } from '../../components/ui'
import { SkeletonCard } from '../../components/ui/Skeleton'

/**
 * Read-only student view of one institution's public directory profile —
 * mirrors the glass-hero + info-card language used by CompanyDetail.tsx.
 * Being listed here means "discoverable," never "a CredChain partner" —
 * there is no admin/management surface on this page.
 */
export function InstitutionDetail() {
  const { id } = useParams<{ id: string }>()
  const [institution, setInstitution] = useState<InstitutionSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [notFound, setNotFound] = useState(false)

  useEffect(() => {
    if (!id) return
    getInstitution(id)
      .then(setInstitution)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 404) setNotFound(true)
        else throw err
      })
      .finally(() => setLoading(false))
  }, [id])

  if (loading) {
    return (
      <div>
        <SkeletonCard lines={2} />
        <div className="mt-6"><SkeletonCard lines={4} /></div>
      </div>
    )
  }
  if (notFound || !institution) {
    return <EmptyState icon={Landmark} title="Institution not found" description="This institution profile could not be loaded." />
  }

  return (
    <div>
      <GlassPanel className="relative mb-6 overflow-hidden p-6">
        <Glow color="primary" size={300} className="-right-14 -top-16" animate={false} />
        <div className="relative flex items-center gap-4">
          <IconTile icon={GraduationCap} tone="primary" size="md" />
          <div>
            <p className="text-[11px] font-bold uppercase tracking-wider text-primary">Institution Directory</p>
            <h1 className="text-2xl font-bold tracking-tight text-ink font-[family-name:var(--font-display)]">{institution.name}</h1>
            <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-muted">
              {institution.is_registered && institution.verification_status === 'verified' ? (
                <Badge tone="good" size="sm">
                  <ShieldCheck className="h-3 w-3" strokeWidth={2.5} /> Verified CredChain Institution
                </Badge>
              ) : institution.is_registered ? (
                <Badge tone="neutral" size="sm" withIcon={false}>
                  Registered — Not Yet Verified
                </Badge>
              ) : (
                <Badge tone="neutral" size="sm" withIcon={false}>
                  Directory Listing
                </Badge>
              )}
              {institution.institution_type && (
                <Badge tone="primary" size="sm" withIcon={false}>
                  {institution.institution_type}
                </Badge>
              )}
              {(institution.location || institution.country) && (
                <span className="flex items-center gap-1"><MapPin className="h-3 w-3" strokeWidth={2} /> {institution.location ?? institution.country}</span>
              )}
            </div>
          </div>
        </div>
      </GlassPanel>

      {!institution.is_registered && (
        <div className="mb-6 flex items-start gap-2.5 rounded-xl border border-line bg-canvas-2/50 px-4 py-3 text-[13px] text-muted">
          <Info className="mt-0.5 h-4 w-4 shrink-0 text-faint" strokeWidth={2} />
          <p>
            This is a discoverable directory listing, not a registered CredChain institution — it has no CredChain login and
            cannot issue credentials through CredChain. The information below is public directory data only.
          </p>
        </div>
      )}

      <GlassPanel className="p-5">
        <h3 className="mb-3 text-sm font-bold text-ink">About</h3>
        <p className="text-[13px] leading-relaxed text-body">{institution.description ?? 'No description is available for this institution yet.'}</p>
        {institution.website && (
          <a
            href={institution.website}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-4 inline-flex items-center gap-1.5 rounded-lg border border-line px-3.5 py-2 text-[13px] font-semibold text-body transition-colors hover:border-primary-line hover:text-ink"
          >
            <Globe className="h-3.5 w-3.5" strokeWidth={2} /> Visit Official Website ↗
          </a>
        )}
      </GlassPanel>
    </div>
  )
}
