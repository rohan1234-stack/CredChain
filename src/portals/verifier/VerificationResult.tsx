import { useEffect, useState, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { FlaskConical, RotateCcw, ShieldCheck } from 'lucide-react'
import { verifyCredential } from '../../lib/api'
import { ApiError } from '../../lib/apiClient'
import type { BundleVerificationResult, Credential, VerifyCredentialResponse, VerificationChecksResult } from '../../types'
import { PageHeader, Card, Button } from '../../components/ui'
import { SkeletonCard } from '../../components/ui/Skeleton'
import { ResultCard } from './components/ResultCard'

const CHECK_LABELS: { key: keyof VerificationChecksResult; label: string; description: string }[] = [
  { key: 'issuer', label: 'Issuer identity confirmed', description: 'The signing institution is a real, registered issuer on CredChain.' },
  { key: 'signature', label: 'Digital signature valid', description: 'The Ed25519 signature matches the credential exactly as issued.' },
  { key: 'integrity', label: 'Document unaltered', description: 'The attached document matches the exact file that was signed at issuance.' },
  { key: 'status', label: 'Status: active', description: 'The institution has not revoked this credential since issuance.' },
  { key: 'access', label: 'Access authorized', description: 'This viewer holds a valid, unexpired grant to see this credential.' },
]

/**
 * Maps the real backend's verify response onto the ResultCard's display
 * shape. Never fabricates a candidate name — the backend deliberately
 * doesn't return student PII to a verifier.
 *
 * `id` is set to the real internal credential UUID (the route param this
 * page was loaded with), NOT resp.credential.credential_identifier (a
 * human-readable string like "CRD-xxxx") — the view/download endpoints
 * require the real UUID, and the verify response deliberately doesn't
 * re-expose it.
 */
function mapVerifyResponse(resp: VerifyCredentialResponse, credentialId: string): BundleVerificationResult {
  const credentials: Credential[] = resp.credential
    ? [
        {
          id: credentialId,
          type: resp.credential.credential_type,
          title: resp.credential.title,
          issuer: resp.credential.institution_name,
          issuedTo: '',
          issuedDate: resp.credential.graduation_year ? String(resp.credential.graduation_year) : '',
          status: 'verified',
          cgpa: resp.credential.cgpa ?? undefined,
          documentUrl: '#',
          fields: [],
        },
      ]
    : []

  return {
    status: resp.result,
    credentials,
    checks: CHECK_LABELS.map(({ key, label, description }) => ({ label, passed: resp.checks[key], description })),
    blockchain: resp.blockchain,
    requestedCredentials: resp.requested_credentials,
  }
}

export function VerificationResult() {
  const { credentialId } = useParams<{ credentialId: string }>()

  const [result, setResult] = useState<BundleVerificationResult | null>(null)
  const [cgpaInput, setCgpaInput] = useState('')
  const [loading, setLoading] = useState(true)
  const [rerunning, setRerunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const runCheck = useCallback(async () => {
    if (!credentialId) return
    setError(null)
    try {
      const resp = await verifyCredential(credentialId)
      setResult(mapVerifyResponse(resp, credentialId))
      if (resp.credential?.cgpa != null) setCgpaInput(String(resp.credential.cgpa))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Verification request failed.')
    } finally {
      setLoading(false)
    }
  }, [credentialId])

  useEffect(() => {
    runCheck()
  }, [runCheck])

  async function handleRerun() {
    if (!credentialId) return
    setRerunning(true)
    setError(null)
    try {
      // Real tamper demonstration: the backend reconstructs the canonical
      // payload with THIS cgpa substituted in and checks it against the
      // credential's real stored signature — the stored credential itself
      // is never touched (see backend/app/services/verification_service.py).
      const resp = await verifyCredential(credentialId, Number(cgpaInput))
      setResult(mapVerifyResponse(resp, credentialId))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Verification request failed.')
    } finally {
      setRerunning(false)
    }
  }

  async function handleReset() {
    if (!credentialId) return
    setRerunning(true)
    setError(null)
    try {
      const resp = await verifyCredential(credentialId) // no override — re-verifies the real stored data
      setResult(mapVerifyResponse(resp, credentialId))
      if (resp.credential?.cgpa != null) setCgpaInput(String(resp.credential.cgpa))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Verification request failed.')
    } finally {
      setRerunning(false)
    }
  }

  if (loading) {
    return (
      <div>
        <PageHeader title="Credential Verification" eyebrow="Trust & Verification" icon={ShieldCheck} />
        <div className="max-w-md">
          <SkeletonCard lines={5} />
        </div>
      </div>
    )
  }

  const canDemoTamper = result?.credentials[0]?.cgpa !== undefined

  return (
    <div>
      <PageHeader title="Credential Verification" eyebrow="Trust & Verification" icon={ShieldCheck} description="A cryptographic check against the issuer's signed record — not an assumption from a shared link." />

      {error && <div className="mb-5 max-w-md rounded-lg bg-bad-bg px-3.5 py-2.5 text-[13px] text-bad">{error}</div>}

      <div className="flex flex-col items-start gap-8 lg:flex-row">
        {result && <ResultCard result={result} />}

        {canDemoTamper && (
          <Card className="w-80 border-dashed border-primary-line bg-primary-bg/30 p-5">
            <div className="mb-1 flex items-center gap-1.5 text-xs font-bold text-primary">
              <FlaskConical className="h-3.5 w-3.5" strokeWidth={2.25} />
              DEMO CONTROLS
            </div>
            <p className="mb-4 text-[11px] text-muted">
              Substitutes a different CGPA when reconstructing the canonical payload and re-checks it against the
              real stored signature — the stored credential itself is never modified. This runs the real backend
              verification service.
            </p>

            <label className="mb-1.5 block text-[10px] font-bold uppercase tracking-wider text-faint">
              Transcript CGPA
            </label>
            <div className="flex items-center gap-2">
              <input
                type="number"
                step="0.1"
                min="0"
                max="10"
                value={cgpaInput}
                onChange={(e) => setCgpaInput(e.target.value)}
                className="w-24 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-primary"
              />
            </div>

            <Button variant="solid" size="sm" className="mt-3 w-full" loading={rerunning} onClick={handleRerun}>
              Re-run Verification
            </Button>
            <Button variant="ghost" size="sm" className="mt-2 w-full" icon={<RotateCcw className="h-3.5 w-3.5" />} onClick={handleReset}>
              Reset to original
            </Button>
          </Card>
        )}
      </div>
    </div>
  )
}
