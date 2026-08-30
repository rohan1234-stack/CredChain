import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Plus, FileText } from 'lucide-react'
import { getIssuedCredentials, revokeCredential } from '../../lib/api'
import { ApiError } from '../../lib/apiClient'
import { useAuth } from '../../context/AuthContext'
import type { Credential } from '../../types'
import { PageHeader, Badge, Button, EmptyState, GlassPanel } from '../../components/ui'
import { SkeletonGrid } from '../../components/ui/Skeleton'
import { IconTile } from '../../components/ui/IconTile'
import { CREDENTIAL_TYPE_ICON, credentialStatusTone, credentialStatusLabel } from '../../lib/utils'

/**
 * Reproduces the same "Digital Vault" glass-card language established for
 * the student-side credential list (see student/components/CredentialCard.tsx)
 * — no dedicated Stitch screen exists for the issuer's-eye view, so this
 * inherits that established pattern rather than staying a plain table.
 * Shown here: real recipient student name (not "you"), and a Revoke action
 * in place of View/Share, since this is the institution's registry.
 */
function IssuedCredentialCard({
  credential,
  confirming,
  revoking,
  onRevoke,
  onCancel,
  onConfirm,
}: {
  credential: Credential
  confirming: boolean
  revoking: boolean
  onRevoke: () => void
  onCancel: () => void
  onConfirm: () => void
}) {
  const Icon = CREDENTIAL_TYPE_ICON[credential.type]
  const shortId = credential.id.length > 12 ? `${credential.id.slice(0, 6)}…${credential.id.slice(-4)}` : credential.id
  return (
    <GlassPanel className="group relative overflow-hidden p-4">
      <Icon aria-hidden className="pointer-events-none absolute -bottom-4 -right-4 h-28 w-28 rotate-[-12deg] text-white/[0.03]" strokeWidth={1} />
      <div className="relative mb-4 flex items-start justify-between">
        <IconTile icon={Icon} tone="neutral" size="sm" />
        <Badge tone={credentialStatusTone(credential.status)} size="sm">
          {credentialStatusLabel(credential.status)}
        </Badge>
      </div>
      <div className="relative">
        <h3 className="text-[15px] font-bold leading-snug text-primary">{credential.title}</h3>
        <p className="mt-1 text-xs text-muted">{credential.studentName ?? 'Unknown recipient'}</p>
      </div>
      <div className="relative mt-4 flex items-end justify-between border-t border-white/5 pt-2.5">
        <div>
          <p className="font-[family-name:var(--font-mono)] text-[10px] uppercase tracking-wider text-faint">Issued</p>
          <p className="font-[family-name:var(--font-mono)] text-[13px] text-ink">{credential.issuedDate}</p>
        </div>
        <div className="text-right">
          <p className="font-[family-name:var(--font-mono)] text-[10px] uppercase tracking-wider text-faint">Credential ID</p>
          <p className="font-[family-name:var(--font-mono)] text-[13px] text-cyan">{shortId}</p>
        </div>
      </div>
      {credential.status !== 'revoked' && (
        <div className="relative mt-3">
          {confirming ? (
            <div className="flex items-center gap-2">
              <span className="flex-1 text-[11px] text-muted">Revoke this credential?</span>
              <Button variant="outline" size="sm" disabled={revoking} onClick={onCancel}>
                Cancel
              </Button>
              <Button variant="danger" size="sm" loading={revoking} onClick={onConfirm}>
                Confirm
              </Button>
            </div>
          ) : (
            <Button variant="danger" size="sm" className="w-full" onClick={onRevoke}>
              Revoke
            </Button>
          )}
        </div>
      )}
    </GlassPanel>
  )
}

export function InstitutionCredentialsList() {
  const { user } = useAuth()
  const [credentials, setCredentials] = useState<Credential[]>([])
  const [loading, setLoading] = useState(true)
  const [confirmingId, setConfirmingId] = useState<string | null>(null)
  const [revokingId, setRevokingId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getIssuedCredentials()
      .then(setCredentials)
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Unable to load credentials. Please try again.'))
      .finally(() => setLoading(false))
  }, [])

  async function handleConfirmRevoke(id: string) {
    setRevokingId(id)
    setError(null)
    try {
      // The backend is the source of truth for the resulting state — the
      // row updates from its real response, not a locally-guessed value.
      const updated = await revokeCredential(id)
      setCredentials((prev) => prev.map((c) => (c.id === id ? updated : c)))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not revoke this credential. Please try again.')
    } finally {
      setRevokingId(null)
      setConfirmingId(null)
    }
  }

  if (loading) {
    return (
      <div>
        <PageHeader title="Issued Credentials" eyebrow="Credential Registry" icon={FileText} description=" " />
        <SkeletonGrid count={6} />
      </div>
    )
  }

  return (
    <div>
      <PageHeader
        title="Issued Credentials"
        eyebrow="Credential Registry"
        icon={FileText}
        description={`Every credential ${user?.org_name ?? 'your institution'} has issued.`}
        action={
          <Link to="/institution/credentials/issue">
            <Button variant="solid" icon={<Plus className="h-4 w-4" />}>
              Issue Credential
            </Button>
          </Link>
        }
      />

      {error && <div className="mb-4 max-w-2xl rounded-lg bg-bad-bg px-3.5 py-2.5 text-[13px] text-bad">{error}</div>}

      {credentials.length === 0 ? (
        !error && <EmptyState icon={FileText} title="No credentials issued yet" description="Credentials you issue will be listed here as a real, auditable registry." />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {credentials.map((c) => (
            <IssuedCredentialCard
              key={c.id}
              credential={c}
              confirming={confirmingId === c.id}
              revoking={revokingId === c.id}
              onRevoke={() => setConfirmingId(c.id)}
              onCancel={() => setConfirmingId(null)}
              onConfirm={() => handleConfirmRevoke(c.id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}
