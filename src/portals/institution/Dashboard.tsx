import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Plus, FileText, GraduationCap, Award, ShieldCheck, MailWarning, FileSearch, ShieldAlert, Clock3 } from 'lucide-react'
import { getIssuedCredentials, getStudents, getInstitutionCertificateRequests, getInstitutionDocuments } from '../../lib/api'
import { useAuth } from '../../context/AuthContext'
import type { Credential } from '../../types'
import { Button, Card, Badge, EmptyState, StatCard } from '../../components/ui'
import { SkeletonCard } from '../../components/ui/Skeleton'
import { CREDENTIAL_TYPE_ICON, credentialStatusTone, credentialStatusLabel } from '../../lib/utils'
import { IconTile } from '../../components/ui/IconTile'

/**
 * Reproduces the actual Stitch "institution_dashboard" screen: greeting ->
 * a single obsidian-glass "Secure Network Active" hero panel (emerald glow,
 * shield_lock motif) -> a 2x2 bento metrics grid (two square cards, two
 * full-width left-rail cards) -> recently issued list. See
 * stitch1/institution_dashboard/code.html. Stitch's own screen shows fake
 * "Stanford University" / "14,208 Students" / "42,501 Issued" — every one of
 * those slots below is real data from the existing institution APIs instead.
 */
export function InstitutionDashboard() {
  const { user } = useAuth()
  const [credentials, setCredentials] = useState<Credential[]>([])
  const [studentCount, setStudentCount] = useState(0)
  const [pendingCertRequests, setPendingCertRequests] = useState(0)
  const [underReviewDocs, setUnderReviewDocs] = useState(0)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      getIssuedCredentials().then(setCredentials),
      getStudents().then((s) => setStudentCount(s.length)),
      getInstitutionCertificateRequests().then((reqs) => setPendingCertRequests(reqs.filter((r) => r.status === 'pending').length)),
      getInstitutionDocuments().then((docs) => setUnderReviewDocs(docs.filter((d) => d.status === 'under_review' || d.status === 'unverified').length)),
    ]).finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="space-y-4">
        <SkeletonCard lines={2} />
        <SkeletonCard lines={4} />
      </div>
    )
  }

  return (
    <div>
      {/* Hero greeting */}
      <div className="mb-4 flex flex-col gap-1">
        <h1 className="text-[28px] font-bold leading-tight tracking-tight text-ink font-[family-name:var(--font-display)]">
          Good {new Date().getHours() < 17 ? 'Afternoon' : 'Evening'},{' '}
          <span className="bg-gradient-to-br from-primary to-ai bg-clip-text text-transparent">
            {user?.org_name ?? 'Your Institution'}
          </span>
        </h1>
        <p className="text-base text-muted">Manage trusted academic credentials.</p>
      </div>

      {user?.institution_verification_status === 'pending' && (
        <div className="mb-6 flex items-start gap-3 rounded-xl border border-warn-line bg-warn-bg px-4 py-3.5 text-warn">
          <Clock3 className="mt-0.5 h-5 w-5 shrink-0" strokeWidth={2} />
          <div>
            <p className="text-sm font-semibold">Pending verification</p>
            <p className="text-[13px] leading-relaxed">
              Your institution account is awaiting review by a CredChain administrator. You can browse your dashboard, but credential issuance is
              disabled until your account is approved.
            </p>
          </div>
        </div>
      )}
      {user?.institution_verification_status === 'rejected' && (
        <div className="mb-6 flex items-start gap-3 rounded-xl border border-bad-line bg-bad-bg px-4 py-3.5 text-bad">
          <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0" strokeWidth={2} />
          <div>
            <p className="text-sm font-semibold">Verification rejected</p>
            <p className="text-[13px] leading-relaxed">
              {user.institution_rejection_reason || 'Your institution account was not approved.'} Credential issuance is disabled.
            </p>
          </div>
        </div>
      )}

      {/* Visual hero object — Stitch's "Secure Network Active" obsidian-emerald panel,
          reproduced with CSS/SVG glow rather than the fictional illustration asset. */}
      <div className="relative mb-6 flex w-full items-center justify-center overflow-hidden rounded-xl border border-good-line px-6 py-8"
        style={{ background: 'radial-gradient(ellipse at center, rgba(0,56,36,0.35) 0%, rgba(10,15,30,0.7) 70%)', backdropFilter: 'blur(20px)' }}
      >
        <div aria-hidden className="absolute -left-10 -top-10 h-48 w-48 rounded-full bg-good/15 blur-[80px]" />
        <div aria-hidden className="absolute -bottom-10 -right-10 h-48 w-48 rounded-full bg-primary/15 blur-[80px]" />
        <div className="relative flex flex-col items-center gap-2.5 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-full bg-good/10 text-good shadow-[0_0_24px_rgba(78,222,163,0.5)]">
            <ShieldCheck className="h-7 w-7" strokeWidth={2} />
          </div>
          <p className="text-xl font-semibold text-ink">Secure Network Active</p>
          <p className="rounded-full border border-good-line bg-good-bg px-3 py-1 font-[family-name:var(--font-mono)] text-[13px] text-good">
            {credentials.length} credentials signed
          </p>
        </div>
      </div>

      {/* Metrics bento grid — 2 square cards then 2 full-width rail cards, matching Stitch exactly */}
      <div className="mb-6 grid grid-cols-2 gap-3">
        <StatCard value={studentCount} label="Students" icon={GraduationCap} />
        <StatCard value={credentials.length} label="Credentials Issued" icon={Award} tone="primary" />
        <div className="col-span-2">
          <Link to="/institution/certificate-requests">
            <Card className="flex flex-row items-center justify-between gap-4 border-l-2 border-l-cyan p-4">
              <div className="flex items-center gap-4">
                <div className="flex h-12 w-12 items-center justify-center rounded-full bg-cyan-bg">
                  <MailWarning className="h-5 w-5 text-cyan" strokeWidth={2} />
                </div>
                <div>
                  <p className="text-base font-semibold text-ink">Pending Requests</p>
                  <p className="text-sm text-muted">Certificate verification needed</p>
                </div>
              </div>
              <span className="text-2xl font-bold tabular-nums text-cyan font-[family-name:var(--font-display)]">{pendingCertRequests}</span>
            </Card>
          </Link>
        </div>
        <div className="col-span-2">
          <Link to="/institution/documents">
            <Card className="flex flex-row items-center justify-between gap-4 border-l-2 border-l-bad p-4">
              <div className="flex items-center gap-4">
                <div className="flex h-12 w-12 items-center justify-center rounded-full bg-bad-bg">
                  <FileSearch className="h-5 w-5 text-bad" strokeWidth={2} />
                </div>
                <div>
                  <p className="text-base font-semibold text-ink">Under Review</p>
                  <p className="text-sm text-muted">Uploaded documents awaiting review</p>
                </div>
              </div>
              <span className="text-2xl font-bold tabular-nums text-bad font-[family-name:var(--font-display)]">{underReviewDocs}</span>
            </Card>
          </Link>
        </div>
      </div>

      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-[15px] font-bold text-ink">Recently Issued</h2>
        {user?.institution_verification_status === 'verified' ? (
          <Link to="/institution/credentials/issue">
            <Button variant="solid" size="sm" icon={<Plus className="h-4 w-4" />}>
              Issue Credential
            </Button>
          </Link>
        ) : (
          <Button variant="solid" size="sm" icon={<Plus className="h-4 w-4" />} disabled>
            Issue Credential
          </Button>
        )}
      </div>
      {credentials.length === 0 ? (
        <EmptyState icon={FileText} title="No credentials yet" description="Credentials you issue will appear here." />
      ) : (
        <Card className="overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line bg-canvas-2/50 text-left text-[11px] font-bold uppercase tracking-wider text-faint">
                <th className="px-5 py-3">Credential</th>
                <th className="px-5 py-3">Student</th>
                <th className="px-5 py-3">Issued</th>
                <th className="px-5 py-3">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {credentials.map((c) => {
                const Icon = CREDENTIAL_TYPE_ICON[c.type]
                return (
                  <tr key={c.id}>
                    <td className="px-5 py-3">
                      <div className="flex items-center gap-2.5">
                        <IconTile icon={Icon} tone="neutral" size="sm" />
                        <span className="font-medium text-ink">{c.title}</span>
                      </div>
                    </td>
                    <td className="px-5 py-3 text-body">{c.studentName ?? '—'}</td>
                    <td className="px-5 py-3 text-body">{c.issuedDate}</td>
                    <td className="px-5 py-3">
                      <Badge tone={credentialStatusTone(c.status)} size="sm">
                        {credentialStatusLabel(c.status)}
                      </Badge>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  )
}
