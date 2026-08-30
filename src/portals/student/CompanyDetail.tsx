import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { Briefcase, Building2, MapPin, Users, Globe, ArrowRight, ShieldCheck, Info } from 'lucide-react'
import { getRealCompany, getOpenJobs } from '../../lib/api'
import type { Company, Job } from '../../types'
import { EmptyState, GlassPanel, Glow, IconTile, Badge } from '../../components/ui'
import { SkeletonCard } from '../../components/ui/Skeleton'

/**
 * No dedicated Stitch screen exists for a single-company profile view —
 * inherits the glass-hero + info-card language established for
 * company_profile_settings (the company's own editable profile, see the
 * rebuilt src/portals/verifier/Profile.tsx) adapted to a read-only student
 * view: an identity hero (icon tile, name, industry/location/size chips)
 * over an "About" panel and the real open-jobs list.
 */
export function CompanyDetail() {
  const { id } = useParams<{ id: string }>()
  const [company, setCompany] = useState<Company | null>(null)
  const [jobs, setJobs] = useState<Job[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!id) return
    Promise.all([getRealCompany(id), getOpenJobs({ companyId: id })])
      .then(([c, companyJobs]) => {
        setCompany(c)
        setJobs(companyJobs)
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
  if (!company) return <EmptyState icon={Briefcase} title="Company not found" description="This company profile could not be loaded." />

  return (
    <div>
      <GlassPanel className="relative mb-6 overflow-hidden p-6">
        <Glow color="ai" size={300} className="-right-14 -top-16" animate={false} />
        <div className="relative flex items-center gap-4">
          <IconTile icon={Building2} tone="ai" size="md" />
          <div>
            <p className="text-[11px] font-bold uppercase tracking-wider text-ai">Employer Profile</p>
            <h1 className="text-2xl font-bold tracking-tight text-ink font-[family-name:var(--font-display)]">{company.name}</h1>
            <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-muted">
              {company.is_registered && company.verification_status === 'verified' ? (
                <Badge tone="good" size="sm">
                  <ShieldCheck className="h-3 w-3" strokeWidth={2.5} /> Verified CredChain Employer
                </Badge>
              ) : company.is_registered ? (
                <Badge tone="neutral" size="sm" withIcon={false}>
                  Registered — Not Yet Verified
                </Badge>
              ) : (
                <Badge tone="neutral" size="sm" withIcon={false}>
                  External Company
                </Badge>
              )}
              {company.industry && (
                <span className="flex items-center gap-1"><Briefcase className="h-3 w-3" strokeWidth={2} /> {company.industry}</span>
              )}
              {(company.location || company.country) && (
                <span className="flex items-center gap-1"><MapPin className="h-3 w-3" strokeWidth={2} /> {company.location ?? company.country}</span>
              )}
              {company.company_size && (
                <span className="flex items-center gap-1"><Users className="h-3 w-3" strokeWidth={2} /> {company.company_size} employees</span>
              )}
            </div>
          </div>
        </div>
      </GlassPanel>

      {!company.is_registered && (
        <div className="mb-6 flex items-start gap-2.5 rounded-xl border border-line bg-canvas-2/50 px-4 py-3 text-[13px] text-muted">
          <Info className="mt-0.5 h-4 w-4 shrink-0 text-faint" strokeWidth={2} />
          <p>
            This is a discoverable directory listing, not a registered CredChain employer — it has no CredChain login and cannot
            post jobs or receive applications through CredChain. Any open positions below are only ever real CredChain job postings.
          </p>
        </div>
      )}

      <div className="grid grid-cols-1 gap-5">
        <GlassPanel className="p-5">
          <h3 className="mb-3 text-sm font-bold text-ink">About</h3>
          <p className="text-[13px] leading-relaxed text-body">{company.description ?? 'This company has not added a description yet.'}</p>
          {company.website && (
            <a href={company.website} target="_blank" rel="noopener noreferrer" className="mt-3 inline-flex items-center gap-1.5 text-[13px] font-semibold text-primary hover:underline">
              <Globe className="h-3.5 w-3.5" strokeWidth={2} /> {company.website}
            </a>
          )}
        </GlassPanel>

        <div>
          <h3 className="mb-3 text-sm font-bold text-ink">Open Positions</h3>
          {jobs.length === 0 ? (
            <EmptyState icon={Briefcase} title="No open positions" description="This company has no open jobs right now." />
          ) : (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {jobs.map((j) => (
                <Link key={j.id} to={`/student/jobs/${j.id}`} className="group">
                  <GlassPanel className="flex items-center justify-between gap-3 p-4 transition-transform duration-200 group-hover:-translate-y-0.5 group-hover:border-primary-line">
                    <div className="min-w-0">
                      <p className="truncate font-semibold text-ink">{j.title}</p>
                      <p className="text-xs text-muted">{j.location ?? 'Location not specified'}</p>
                    </div>
                    <ArrowRight className="h-4 w-4 shrink-0 text-faint opacity-0 transition-opacity group-hover:opacity-100" />
                  </GlassPanel>
                </Link>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
