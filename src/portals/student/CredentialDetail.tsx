import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { ArrowLeft, Lock, Info, FileText, Share2, CheckCircle2 } from 'lucide-react'
import { getCredential, getCredentialDocument } from '../../lib/api'
import { ApiError } from '../../lib/apiClient'
import type { Credential } from '../../types'
import { Badge, Button, GlassPanel, Glow, EmptyState, ErrorState } from '../../components/ui'
import { SkeletonCard } from '../../components/ui/Skeleton'
import { credentialStatusTone, credentialStatusLabel, CREDENTIAL_TYPE_ICON } from '../../lib/utils'
import { CredentialBlockchainBadge } from '../../components/blockchain/BlockchainProof'

/**
 * Reproduces Stitch's "credential_detail" screen structure (see
 * stitch1/credential_detail/code.html): a cinematic certificate hero (status
 * chip row, big title/issuer, 3-column meta strip, circular rotating seal)
 * above a 2/3 + 1/3 bento grid — Academic Details + Document Preview on the
 * left, Verification + Share Proof on the right. Stitch's own reference
 * hardcodes "Stanford University" / "Alex Mercer" / a fake transaction hash
 * / "Ethereum Mainnet" — every one of those slots below uses the real
 * credential prop or the existing CredentialBlockchainBadge, which already
 * shows the honest "Not anchored" state when there is no real chain proof.
 */

export function CredentialDetail() {
  const { id } = useParams<{ id: string }>()
  const [credential, setCredential] = useState<Credential | null>(null)
  const [loading, setLoading] = useState(true)
  const [notFound, setNotFound] = useState(false)
  const [error, setError] = useState<{ title: string; message: string } | null>(null)
  const [documentLoading, setDocumentLoading] = useState(false)
  const [documentError, setDocumentError] = useState<string | null>(null)

  function load() {
    if (!id) return
    // Resetting loading/notFound/error before each fetch (both on id change and on
    // manual Retry) is the actual intended behavior here, not an accidental cascading render.
    // oxlint-disable-next-line react/set-state-in-effect
    setLoading(true)
    setNotFound(false)
    setError(null)
    getCredential(id)
      .then((c) => {
        if (!c) setNotFound(true)
        else setCredential(c)
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 403) {
          setError({ title: 'Access denied', message: err.message })
        } else if (err instanceof ApiError) {
          setError({ title: 'Something went wrong', message: err.message })
        } else {
          setError({ title: 'Something went wrong', message: 'Could not load this credential. Please try again.' })
        }
      })
      .finally(() => setLoading(false))
  }

  useEffect(load, [id])

  async function handleViewDocument() {
    if (!id) return
    setDocumentError(null)
    setDocumentLoading(true)
    try {
      const blob = await getCredentialDocument(id)
      const url = URL.createObjectURL(blob)
      window.open(url, '_blank')
      // Revoke once the browser has had a chance to load it into the new tab.
      setTimeout(() => URL.revokeObjectURL(url), 30_000)
    } catch (err) {
      setDocumentError(err instanceof ApiError ? err.message : 'Could not load the document.')
    } finally {
      setDocumentLoading(false)
    }
  }

  if (loading) {
    return (
      <div>
        <SkeletonCard lines={2} />
        <div className="mt-6"><SkeletonCard lines={5} /></div>
      </div>
    )
  }

  if (notFound) {
    return <EmptyState icon={FileText} title="Credential not found" description="This credential could not be found." />
  }

  if (error) {
    return <ErrorState title={error.title} description={error.message} onRetry={load} />
  }

  if (!credential) return null

  const isVerified = credential.status === 'verified'
  const TypeIcon = CREDENTIAL_TYPE_ICON[credential.type]

  return (
    <div>
      <Link to="/student/credentials" className="mb-4 inline-flex items-center gap-1 text-xs font-semibold text-muted hover:text-ink">
        <ArrowLeft className="h-3.5 w-3.5" /> Back to Credential Passport
      </Link>

      {/* Cinematic certificate hero */}
      <GlassPanel className="relative mb-6 overflow-hidden p-6 sm:p-8" glow>
        <Glow color="primary" size={380} className="-right-20 -top-24" animate={false} />
        <div aria-hidden className="pointer-events-none absolute inset-0 [background-image:radial-gradient(rgba(255,255,255,0.06)_1px,transparent_1px)] [background-size:24px_24px]" />
        <div className="relative flex flex-col items-center gap-8 md:flex-row md:justify-between">
          <div className="flex-1">
            <div className="flex flex-wrap items-center gap-3">
              <Badge tone={credentialStatusTone(credential.status)}>{credentialStatusLabel(credential.status)}</Badge>
              {isVerified && (
                <span className="flex items-center gap-1.5 font-[family-name:var(--font-mono)] text-[12px] text-muted">
                  <span className="h-2 w-2 animate-pulse rounded-full bg-cyan" />
                  Live Sync
                </span>
              )}
            </div>
            <h1 className="mt-3 text-2xl font-bold leading-tight tracking-tight text-primary font-[family-name:var(--font-display)] sm:text-[32px]">
              {credential.title}
            </h1>
            <p className="mt-1 text-lg text-muted">{credential.issuer}</p>

            <div className="mt-5 flex flex-wrap gap-6">
              <div>
                <p className="text-[11px] font-bold uppercase tracking-wider text-faint">Issue Date</p>
                <p className="mt-0.5 font-[family-name:var(--font-mono)] text-[13px] text-ink">{credential.issuedDate}</p>
              </div>
              <div>
                <p className="text-[11px] font-bold uppercase tracking-wider text-faint">Recipient</p>
                <p className="mt-0.5 font-[family-name:var(--font-mono)] text-[13px] text-ink">{credential.studentName ?? '—'}</p>
              </div>
              <div>
                <p className="text-[11px] font-bold uppercase tracking-wider text-faint">Credential ID</p>
                <p className="mt-0.5 font-[family-name:var(--font-mono)] text-[13px] text-ink">{credential.id.slice(0, 8)}…{credential.id.slice(-4)}</p>
              </div>
            </div>
          </div>

          {/* Rotating circular seal — Stitch's 3D ribbon motif, built from CSS gradient + perspective */}
          <div className="perspective-1000 relative h-40 w-40 shrink-0 sm:h-52 sm:w-52">
            <div className="preserve-3d h-full w-full rounded-full bg-gradient-to-br from-primary to-ai p-1 shadow-[0_0_40px_-4px_var(--color-primary)] transition-transform duration-500 hover:[transform:rotateY(12deg)]">
              <div className="flex h-full w-full items-center justify-center rounded-full border-4 border-surface bg-canvas-2">
                <TypeIcon className="h-16 w-16 text-primary sm:h-20 sm:w-20" strokeWidth={1.5} />
              </div>
            </div>
          </div>
        </div>
      </GlassPanel>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Left: Academic Details + Document */}
        <div className="space-y-6 lg:col-span-2">
          <GlassPanel className="p-5">
            <h3 className="mb-3 flex items-center gap-2 border-b border-line pb-2.5 text-sm font-bold text-ink">
              <Info className="h-4 w-4 text-cyan" strokeWidth={2} />
              Academic Details
            </h3>
            <dl className="divide-y divide-line">
              {credential.fields.map((f) => (
                <div key={f.label} className="flex items-center justify-between py-3 text-sm">
                  <dt className="text-muted">{f.label}</dt>
                  <dd className="font-[family-name:var(--font-mono)] font-semibold text-ink">{f.value}</dd>
                </div>
              ))}
            </dl>
          </GlassPanel>

          <GlassPanel className="p-5">
            <h3 className="mb-3 flex items-center gap-2 text-sm font-bold text-ink">
              <FileText className="h-4 w-4 text-cyan" strokeWidth={2} />
              Original Document
            </h3>
            <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-line bg-canvas-2/60 py-10 text-center">
              <TypeIcon className="h-10 w-10 text-faint" strokeWidth={1.5} />
              <Button variant="outline" size="sm" loading={documentLoading} onClick={handleViewDocument}>
                View Full Document
              </Button>
              {documentError && <p className="text-[13px] text-bad">{documentError}</p>}
            </div>
          </GlassPanel>
        </div>

        {/* Right: Verification + Share */}
        <div className="space-y-6">
          <GlassPanel className="p-5">
            <h3 className="mb-3 flex items-center gap-2 border-b border-line pb-2.5 text-sm font-bold text-ink">
              <Lock className="h-4 w-4 text-good" strokeWidth={2} />
              Verification
            </h3>
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-good-line bg-good-bg">
                <CheckCircle2 className="h-5 w-5 text-good" strokeWidth={2} />
              </div>
              <div>
                <p className="text-[13px] text-ink">{isVerified ? 'Cryptographic Signature Valid' : `Status: ${credentialStatusLabel(credential.status)}`}</p>
                <p className="text-[11px] text-faint">Signed by {credential.issuer}</p>
              </div>
            </div>
            <div className="mt-4 border-t border-line pt-4">
              <CredentialBlockchainBadge blockchain={credential.blockchain} />
            </div>
          </GlassPanel>

          <GlassPanel className="p-5">
            <h3 className="mb-3 flex items-center gap-2 border-b border-line pb-2.5 text-sm font-bold text-ink">
              <Share2 className="h-4 w-4 text-cyan" strokeWidth={2} />
              Share Proof
            </h3>
            <p className="mb-4 text-[13px] leading-relaxed text-muted">
              Choose a recipient, a permission level, and an expiry — CredChain generates a real, scannable QR and
              link for exactly this credential.
            </p>
            <Link to={`/student/share?ids=${credential.id}`}>
              <Button variant="solid" className="w-full">
                Share Credential
              </Button>
            </Link>
          </GlassPanel>
        </div>
      </div>
    </div>
  )
}
