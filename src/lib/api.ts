// ---------------------------------------------------------------------------
// Mock API layer.
//
// Every function here returns a Promise, mirrors what a real REST/GraphQL
// call would look like, and reads/writes the in-memory store. Swapping to a
// real backend tomorrow means replacing function *bodies* with fetch() calls
// — the signatures and return shapes should not need to change.
// ---------------------------------------------------------------------------

import type {
  Credential,
  AccessLogEntry,
  Company,
  CredentialType,
  CredentialStatus,
  AuthUser,
  AuthTokenResponse,
  RegisterPayload,
  InstitutionSummary,
  BackendCredential,
  BackendStudentSummary,
  VerifyCredentialResponse,
  BackendCredentialRequest,
  BackendShareGrant,
  ShareCreatedResult,
  ShareTokenAccessResult,
  SharedCredentialItem,
  SharedCredentialStatusFilter,
  AiHealthResult,
  AiDocumentRequirementsResult,
  AiCompanyIntelligenceResult,
  AiCredentialMatchResult,
  BackendActivityEvent,
  InstitutionCertificateRequest,
  StudentDocument,
  NotificationCounts,
  AppNotification,
  Job,
  CreateJobInput,
  UpdateCompanyProfileInput,
  StudentJobApplication,
  CompanyJobApplication,
  JobAIAnalysisResult,
  Page,
  PendingInstitution,
  PendingCompany,
} from '../types'
import {
  credentials,
} from './mockStore'
import { apiClient, ApiError } from './apiClient'

const delay = (ms = 250) => new Promise((res) => setTimeout(res, ms))

// ---- Auth (real backend — everything else below this section is still the
// mock layer described above, wired to real FastAPI endpoints starting
// Phase 4+) ------------------------------------------------------------------

export async function login(email: string, password: string): Promise<AuthTokenResponse> {
  return apiClient.post<AuthTokenResponse>('/auth/login', { email, password })
}

export async function register(payload: RegisterPayload): Promise<AuthTokenResponse> {
  return apiClient.post<AuthTokenResponse>('/auth/register', payload)
}

function toQueryString(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') search.set(key, String(value))
  }
  const qs = search.toString()
  return qs ? `?${qs}` : ''
}

// The backend directory endpoints (GET /institutions, GET /companies) are always paginated
// (see backend/app/schemas/pagination.py) — this is the page size the handful of "just give me
// the full pick-list" callers (registration's institution picker, the direct-share company
// picker) request so they keep behaving like a complete list without needing their own
// pagination UI. The dedicated Directory pages (Institutions.tsx/Companies.tsx) use
// getInstitutionsPage/getCompaniesPage below for real, page-by-page browsing of the whole
// (potentially tens-of-thousands-of-rows) dataset instead.
const LEGACY_FULL_LIST_PAGE_SIZE = 100

/**
 * Public — real institutions, unwrapped to a plain array. Used by the
 * registration/link-institution picker and the direct-share company picker
 * equivalents — anywhere that predates pagination and just wants "the
 * list." See getInstitutionsPage for the real paginated directory query.
 */
export async function getInstitutions(filters?: { search?: string; location?: string; country?: string }): Promise<InstitutionSummary[]> {
  const page = await apiClient.get<Page<InstitutionSummary>>(
    `/institutions${toQueryString({ ...filters, page_size: LEGACY_FULL_LIST_PAGE_SIZE })}`
  )
  return page.items
}

/** Public — one page of the institution directory, with the real total/page_count for pagination controls. */
export async function getInstitutionsPage(params?: {
  search?: string
  location?: string
  country?: string
  region?: string
  institutionType?: string
  page?: number
  pageSize?: number
}): Promise<Page<InstitutionSummary>> {
  return apiClient.get<Page<InstitutionSummary>>(
    `/institutions${toQueryString({
      search: params?.search,
      location: params?.location,
      country: params?.country,
      region: params?.region,
      institution_type: params?.institutionType,
      page: params?.page,
      page_size: params?.pageSize,
    })}`
  )
}

/** Public — one institution's directory profile. */
export async function getInstitution(id: string): Promise<InstitutionSummary> {
  return apiClient.get<InstitutionSummary>(`/institutions/${id}`)
}

/** Links (or re-links) the authenticated student to a real institution, validated server-side. */
export async function linkInstitution(institutionId: string): Promise<{ institution_id: string; institution_name: string }> {
  return apiClient.post('/students/me/institution', { institution_id: institutionId })
}

export async function getCurrentUser(): Promise<AuthUser> {
  return apiClient.get<AuthUser>('/auth/me')
}

export async function logout(): Promise<void> {
  await apiClient.post('/auth/logout')
}

// ---- Credentials (real backend) --------------------------------------------
//
// Backend credential status is active|revoked|expired (its own lifecycle
// vocabulary); the frontend's Credential.status is verified|pending|revoked
// (carried over from the original mock design, see README's "Credential
// status vocabulary" note). 'expired' has no frontend-side rendering yet
// (Phase 6 territory — share/access expiry, not credential expiry) so it
// maps to 'revoked' as the nearest safe rendering rather than inventing a
// new UI state this phase didn't ask for.
function mapBackendStatus(status: BackendCredential['status']): CredentialStatus {
  if (status === 'active') return 'verified'
  return 'revoked'
}

function mapBackendCredential(c: BackendCredential): Credential {
  const fields: { label: string; value: string }[] = [{ label: 'Issued by', value: c.institution_name }]
  if (c.degree) fields.push({ label: 'Degree', value: c.degree })
  else fields.push({ label: 'Credential', value: c.title })
  if (c.graduation_year) fields.push({ label: 'Graduation', value: String(c.graduation_year) })
  fields.push({ label: 'Issued', value: String(new Date(c.issued_at).getFullYear()) })
  if (c.cgpa !== null) fields.push({ label: 'CGPA', value: String(c.cgpa) })

  return {
    id: c.id,
    type: c.credential_type,
    title: c.title,
    issuer: c.institution_name,
    issuedTo: c.student_id,
    issuedDate: String(new Date(c.issued_at).getFullYear()),
    status: mapBackendStatus(c.status),
    cgpa: c.cgpa ?? undefined,
    originalCgpa: c.cgpa ?? undefined,
    documentUrl: c.has_document ? `/credentials/${c.id}/document` : '#',
    fields,
    studentName: c.student_name,
    blockchain: {
      status: c.blockchain_status,
      network: c.blockchain_network,
      contractAddress: c.blockchain_contract_address,
      transactionHash: c.blockchain_tx_hash,
      anchoredAt: c.blockchain_anchored_at,
    },
  }
}

// ---- Student: credentials -------------------------------------------------

export async function getCredentials(): Promise<Credential[]> {
  const data = await apiClient.get<BackendCredential[]>('/students/me/credentials')
  return data.map(mapBackendCredential)
}

export async function getCredential(id: string): Promise<Credential | undefined> {
  try {
    const data = await apiClient.get<BackendCredential>(`/credentials/${id}`)
    return mapBackendCredential(data)
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return undefined
    throw err
  }
}

/** Fetches the credential's document as a Blob (protected — requires auth). Caller is responsible for creating/revoking an object URL. */
export async function getCredentialDocument(id: string): Promise<Blob> {
  return apiClient.getBlob(`/credentials/${id}/document`)
}

// ---- Credential requests + selective sharing (real backend, Phase 6) --------
//
// Creating a request never grants access by itself — a ShareGrant only
// comes into existence when the student explicitly approves and picks
// which credentials to include (approveCredentialRequest below). Nothing
// here uses setTimeout/fake tokens/in-memory arrays — every call hits the
// real backend, which is the sole source of truth for requests and shares.

export async function sendCredentialRequest(input: {
  studentIdentifier: string
  purpose: string
  requestedCredentials: string[]
}): Promise<BackendCredentialRequest> {
  return apiClient.post<BackendCredentialRequest>('/credential-requests', {
    student_identifier: input.studentIdentifier,
    purpose: input.purpose,
    requested_credentials: input.requestedCredentials,
  })
}

export async function getCompanyRequests(): Promise<BackendCredentialRequest[]> {
  return apiClient.get<BackendCredentialRequest[]>('/companies/me/requests')
}

export async function getStudentRequests(): Promise<BackendCredentialRequest[]> {
  return apiClient.get<BackendCredentialRequest[]>('/students/me/requests')
}

export async function declineCredentialRequest(requestId: string): Promise<BackendCredentialRequest> {
  return apiClient.post<BackendCredentialRequest>(`/credential-requests/${requestId}/decline`)
}

/** Student explicitly selects which credentials to include (credentialIds) — only those become part of the ShareGrant, regardless of what was originally requested. */
export async function approveCredentialRequest(
  requestId: string,
  credentialIds: string[],
  expiresInDays: number,
  permission: 'view_only' | 'view_download' = 'view_only'
): Promise<ShareCreatedResult> {
  return apiClient.post<ShareCreatedResult>(`/credential-requests/${requestId}/approve`, {
    credential_ids: credentialIds,
    expires_in_days: expiresInDays,
    permission,
  })
}

export async function getStudentShares(): Promise<BackendShareGrant[]> {
  return apiClient.get<BackendShareGrant[]>('/students/me/shares')
}

export async function getCompanyShares(): Promise<BackendShareGrant[]> {
  return apiClient.get<BackendShareGrant[]>('/companies/me/shares')
}

/** Paginated, searchable, filterable "Credentials Shared With You" inbox — never loads more than one page. */
export async function getSharedCredentialsPage(params?: {
  search?: string
  status?: SharedCredentialStatusFilter
  page?: number
  pageSize?: number
}): Promise<Page<SharedCredentialItem>> {
  return apiClient.get<Page<SharedCredentialItem>>(
    `/companies/me/shared-credentials${toQueryString({
      search: params?.search,
      status: params?.status,
      page: params?.page,
      page_size: params?.pageSize,
    })}`
  )
}

export async function revokeShare(shareId: string): Promise<BackendShareGrant> {
  return apiClient.post<BackendShareGrant>(`/shares/${shareId}/revoke`)
}

/** No auth required — the token itself is the authorization (a share-link/QR pattern). Read-only preview; does not perform cryptographic verification (see verifyCredential). */
export async function accessShareByToken(token: string): Promise<ShareTokenAccessResult> {
  return apiClient.get<ShareTokenAccessResult>(`/shares/verify/${token}`)
}

/**
 * Student-initiated share directly to a real company — no prior
 * CredentialRequest exists. Real backend call, same ShareGrant/token
 * architecture as approveCredentialRequest; company_id must be a real
 * company (see getRealCompanies), not free text.
 */
export async function createDirectShare(
  companyId: string,
  credentialIds: string[],
  expiresInDays: number,
  permission: 'view_only' | 'view_download' = 'view_only'
): Promise<ShareCreatedResult> {
  return apiClient.post<ShareCreatedResult>('/students/me/shares', {
    company_id: companyId,
    credential_ids: credentialIds,
    expires_in_days: expiresInDays,
    permission,
  })
}

// ---- Activity (Phase 8B — real backend, all three roles) --------------------
//
// The backend already renders a clean human-readable `message` per row (see
// activity_service.render_message) — that becomes the bold title here. The
// existing AccessLogEntry shape/UI is kept as-is; only the data source
// changes from the mock accessLog/institutionActivity arrays to real
// GET /api/{role}/me/activity calls.

// Real entity_type values written by the backend (see activity_service.py's
// get_*_activity conditions and every ActivityLog(...) call site) — never
// shown raw in the UI, always passed through this map first.
const ACTIVITY_ENTITY_LABEL: Record<string, string> = {
  credential: 'Credential',
  credential_request: 'Credential Request',
  share_grant: 'Credential Share',
  job_application: 'Job Application',
  institution_certificate_request: 'Certificate Request',
  student_document: 'Student Document',
  institution: 'Institution',
  company: 'Company',
  ai_analysis: 'AI Analysis',
}

// Real action values written by the backend (see activity_service.py's
// _GENERIC_MESSAGES and render_message, and every ActivityLog(action=...)
// call site across credential_service, sharing_service, verification_service,
// institution_request_service, student_document_service, job_application_service,
// admin_service, and routes/ai.py). Every action below is a short, human-
// readable event-type label — the small badge/chip shown on each Activity row —
// distinct from `message` (the full rendered sentence) and from the entity
// label above (what the event is ABOUT, vs. what KIND of event it is).
const ACTIVITY_ACTION_LABEL: Record<string, string> = {
  CREDENTIAL_ISSUED: 'Credential Issued',
  CREDENTIAL_REVOKED: 'Credential Revoked',
  CREDENTIAL_VERIFIED: 'Credential Verified',
  CREDENTIAL_SHARED: 'Credential Shared',
  SHARE_REVOKED: 'Credential Share Revoked',
  SHARE_ACCESSED: 'Credential Share Accessed',
  CREDENTIAL_REQUEST_CREATED: 'Credential Request Created',
  CREDENTIAL_REQUEST_APPROVED: 'Credential Request Approved',
  CREDENTIAL_REQUEST_DECLINED: 'Credential Request Declined',
  CERTIFICATE_REQUEST_CREATED: 'Certificate Request Created',
  CERTIFICATE_REQUEST_APPROVED: 'Certificate Request Approved',
  CERTIFICATE_REQUEST_REJECTED: 'Certificate Request Rejected',
  STUDENT_DOCUMENT_SUBMITTED: 'Document Submitted',
  STUDENT_DOCUMENT_APPROVED: 'Document Approved',
  STUDENT_DOCUMENT_REJECTED: 'Document Rejected',
  APPLICATION_SUBMITTED: 'Application Submitted',
  APPLICATION_UNDER_REVIEW: 'Application Under Review',
  APPLICATION_SHORTLISTED: 'Application Shortlisted',
  APPLICATION_ACCEPTED: 'Application Accepted',
  APPLICATION_REJECTED: 'Application Rejected',
  APPLICATION_WITHDRAWN: 'Application Withdrawn',
  ADMIN_APPROVED_INSTITUTION: 'Institution Approved',
  ADMIN_REJECTED_INSTITUTION: 'Institution Rejected',
  ADMIN_APPROVED_COMPANY: 'Company Approved',
  ADMIN_REJECTED_COMPANY: 'Company Rejected',
  AI_DOCUMENT_ANALYSIS: 'AI Document Analysis',
  AI_COMPANY_ANALYSIS: 'AI Company Analysis',
  AI_JOB_ANALYSIS: 'AI Job Analysis',
  AI_JOB_MATCH: 'AI Job Match',
}

const ACTIVITY_CATEGORY: Record<string, AccessLogEntry['category']> = {
  CREDENTIAL_ISSUED: 'credential',
  CREDENTIAL_REVOKED: 'credential',
  CREDENTIAL_VERIFIED: 'verification',
  CREDENTIAL_SHARED: 'sharing',
  SHARE_REVOKED: 'sharing',
  SHARE_ACCESSED: 'sharing',
  CREDENTIAL_REQUEST_CREATED: 'requests',
  CREDENTIAL_REQUEST_APPROVED: 'requests',
  CREDENTIAL_REQUEST_DECLINED: 'requests',
  CERTIFICATE_REQUEST_CREATED: 'requests',
  CERTIFICATE_REQUEST_APPROVED: 'requests',
  CERTIFICATE_REQUEST_REJECTED: 'requests',
  STUDENT_DOCUMENT_SUBMITTED: 'document',
  STUDENT_DOCUMENT_APPROVED: 'document',
  STUDENT_DOCUMENT_REJECTED: 'document',
  APPLICATION_SUBMITTED: 'application',
  APPLICATION_UNDER_REVIEW: 'application',
  APPLICATION_SHORTLISTED: 'application',
  APPLICATION_ACCEPTED: 'application',
  APPLICATION_REJECTED: 'application',
  APPLICATION_WITHDRAWN: 'application',
  ADMIN_APPROVED_INSTITUTION: 'admin',
  ADMIN_REJECTED_INSTITUTION: 'admin',
  ADMIN_APPROVED_COMPANY: 'admin',
  ADMIN_REJECTED_COMPANY: 'admin',
  AI_DOCUMENT_ANALYSIS: 'ai',
  AI_COMPANY_ANALYSIS: 'ai',
  AI_JOB_ANALYSIS: 'ai',
  AI_JOB_MATCH: 'ai',
}

const ACTIVITY_ICON: Record<string, AccessLogEntry['icon']> = {
  CREDENTIAL_ISSUED: 'issued',
  CREDENTIAL_REVOKED: 'revoked',
  CREDENTIAL_VERIFIED: 'verified',
  CREDENTIAL_SHARED: 'shared',
  SHARE_REVOKED: 'revoked',
  SHARE_ACCESSED: 'shared',
  CREDENTIAL_REQUEST_CREATED: 'request',
  CREDENTIAL_REQUEST_APPROVED: 'approved',
  CREDENTIAL_REQUEST_DECLINED: 'declined',
  CERTIFICATE_REQUEST_CREATED: 'request',
  CERTIFICATE_REQUEST_APPROVED: 'approved',
  CERTIFICATE_REQUEST_REJECTED: 'declined',
  STUDENT_DOCUMENT_SUBMITTED: 'document_submitted',
  STUDENT_DOCUMENT_APPROVED: 'approved',
  STUDENT_DOCUMENT_REJECTED: 'declined',
  APPLICATION_SUBMITTED: 'application_submitted',
  APPLICATION_UNDER_REVIEW: 'under_review',
  APPLICATION_SHORTLISTED: 'shortlisted',
  APPLICATION_ACCEPTED: 'approved',
  APPLICATION_REJECTED: 'declined',
  APPLICATION_WITHDRAWN: 'withdrawn',
  ADMIN_APPROVED_INSTITUTION: 'approved',
  ADMIN_REJECTED_INSTITUTION: 'declined',
  ADMIN_APPROVED_COMPANY: 'approved',
  ADMIN_REJECTED_COMPANY: 'declined',
  AI_DOCUMENT_ANALYSIS: 'ai',
  AI_COMPANY_ANALYSIS: 'ai',
  AI_JOB_ANALYSIS: 'ai',
  AI_JOB_MATCH: 'ai',
}

function formatActivityTimestamp(iso: string): string {
  const date = new Date(iso)
  const now = new Date()
  const sameDay = date.toDateString() === now.toDateString()
  if (sameDay) return date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })

  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  if (date.toDateString() === yesterday.toDateString()) return 'Yesterday'

  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function mapBackendActivity(row: BackendActivityEvent): AccessLogEntry {
  // Every action currently emitted anywhere in the backend has an explicit
  // entry in all three maps above — these `??` fallbacks are a defensive
  // catch-all for a hypothetical future action code, not a real code path
  // today. `label`/`icon` fall back to an honestly-generic "Activity"/pulse-
  // icon rather than a specific-looking (and potentially wrong) label like
  // "Issued" or "Approved"; `category` keeps the pre-existing 'sharing'
  // fallback purely for type-safety on this now-unreachable branch.
  return {
    id: row.id,
    category: ACTIVITY_CATEGORY[row.action] ?? 'sharing',
    label: ACTIVITY_ACTION_LABEL[row.action] ?? 'Activity',
    actor: row.entity_type ? (ACTIVITY_ENTITY_LABEL[row.entity_type] ?? row.entity_type) : 'Activity',
    action: row.message,
    timestamp: formatActivityTimestamp(row.created_at),
    icon: ACTIVITY_ICON[row.action] ?? 'activity',
  }
}

// ---- Student: activity ------------------------------------------------------

export async function getActivity(): Promise<AccessLogEntry[]> {
  const data = await apiClient.get<BackendActivityEvent[]>('/students/me/activity')
  return data.map(mapBackendActivity)
}

// ---- Institution: issue / manage (real backend) --------------------------------
//
// The backend performs the actual SHA-256 hashing and Ed25519 signing —
// this function only assembles and sends the multipart request. No
// cryptography happens here or anywhere else in the frontend.

export async function issueCredential(input: {
  studentId: string
  type: CredentialType
  title: string
  degree?: string
  graduationYear?: number
  cgpa?: number
  document: File
  fulfillsRequestId?: string
}): Promise<Credential> {
  const form = new FormData()
  form.append('student_id', input.studentId)
  form.append('credential_type', input.type)
  form.append('title', input.title)
  if (input.degree) form.append('degree', input.degree)
  if (input.graduationYear !== undefined) form.append('graduation_year', String(input.graduationYear))
  if (input.cgpa !== undefined) form.append('cgpa', String(input.cgpa))
  if (input.fulfillsRequestId) form.append('fulfills_request_id', input.fulfillsRequestId)
  form.append('document', input.document)

  const data = await apiClient.postForm<BackendCredential>('/institutions/me/credentials', form)
  return mapBackendCredential(data)
}

// Revocation is out of scope until a later phase (see backend Phase 4 spec's
// explicit "do not implement" list) — this stays mock-only for now, exactly
// as it already was; the Revoke button updates local UI state but does not
// persist server-side yet.
/** Real backend call (Phase 8A) — status change only, persisted in Postgres; never deletes the credential, its document, or its signature. */
export async function revokeCredential(id: string): Promise<Credential> {
  const data = await apiClient.post<BackendCredential>(`/credentials/${id}/revoke`)
  return mapBackendCredential(data)
}

export async function getIssuedCredentials(): Promise<Credential[]> {
  const data = await apiClient.get<BackendCredential[]>('/institutions/me/credentials')
  return data.map(mapBackendCredential)
}

export interface BulkIssuanceItemResult {
  student_id: string
  student_name: string | null
  status: 'issued' | 'failed'
  credential_id: string | null
  error: string | null
}

/** One PDF per student — issues the same credential type/title/metadata to several students in one call. Never all-or-nothing: returns a per-student result list. */
export async function bulkIssueCredentials(input: {
  studentIds: string[]
  documents: File[]
  type: CredentialType
  title: string
  degree?: string
  graduationYear?: number
  cgpa?: number
}): Promise<BulkIssuanceItemResult[]> {
  const form = new FormData()
  input.studentIds.forEach((id) => form.append('student_ids', id))
  input.documents.forEach((doc) => form.append('documents', doc))
  form.append('credential_type', input.type)
  form.append('title', input.title)
  if (input.degree) form.append('degree', input.degree)
  if (input.graduationYear !== undefined) form.append('graduation_year', String(input.graduationYear))
  if (input.cgpa !== undefined) form.append('cgpa', String(input.cgpa))

  const data = await apiClient.postForm<{ results: BulkIssuanceItemResult[] }>('/institutions/me/credentials/bulk', form)
  return data.results
}

export async function getStudents(): Promise<
  { id: string; name: string; identifier: string; initials: string; credentialCount: number }[]
> {
  const data = await apiClient.get<BackendStudentSummary[]>('/institutions/me/students')
  return data.map((s) => ({
    id: s.id,
    name: s.full_name,
    identifier: s.student_identifier,
    initials:
      s.full_name
        .split(' ')
        .map((w) => w[0])
        .filter(Boolean)
        .slice(0, 2)
        .join('')
        .toUpperCase() || '?',
    credentialCount: s.credential_count,
  }))
}

/** Manual-entry fallback for Issue Credential — looks up one of THIS institution's own students by identifier. Throws ApiError(404) if not found/not affiliated. */
export async function getStudentByIdentifier(identifier: string): Promise<{ id: string; name: string }> {
  const data = await apiClient.get<BackendStudentSummary>(
    `/institutions/me/students/lookup/${encodeURIComponent(identifier)}`
  )
  return { id: data.id, name: data.full_name }
}

export async function getInstitutionActivity(): Promise<AccessLogEntry[]> {
  const data = await apiClient.get<BackendActivityEvent[]>('/institutions/me/activity')
  return data.map(mapBackendActivity)
}

// ---- Verifier: activity --------------------------------------

export async function getVerifierActivity(): Promise<AccessLogEntry[]> {
  const data = await apiClient.get<BackendActivityEvent[]>('/companies/me/activity')
  return data.map(mapBackendActivity)
}

// ---- Verifier: real credential verification (Phase 5) -----------------------
//
// Every check (issuer/signature/integrity/status/access) is computed by the
// backend from scratch on every call — this function only sends a
// credential_id (and, for the tamper demo only, an override value) and
// renders whatever the backend decides. Nothing here performs or trusts any
// cryptographic result computed client-side.

export async function verifyCredential(credentialId: string, demoCgpaOverride?: number): Promise<VerifyCredentialResponse> {
  return apiClient.post<VerifyCredentialResponse>('/verification/verify', {
    credential_id: credentialId,
    ...(demoCgpaOverride !== undefined ? { demo_cgpa_override: demoCgpaOverride } : {}),
  })
}

// ---- CredChain AI (real backend, Phase 7) -----------------------------------
//
// Every function here calls the real backend, which itself calls a real LLM
// when AI_ENABLED is configured, or a clearly-labeled deterministic
// fallback otherwise (analysis_mode on every result tells you which ran).
// No keyword matching happens in this file — this is not the old mock
// analyzeRequirements() function (still used, unmodified, by the
// dashboard's small preview widget — this is the real page).

export async function getAiHealth(): Promise<AiHealthResult> {
  return apiClient.get<AiHealthResult>('/ai/health')
}

export async function analyzeDocumentRequirements(input: {
  companyName: string
  jobTitle: string
  jobDescription: string
}): Promise<AiDocumentRequirementsResult> {
  return apiClient.post<AiDocumentRequirementsResult>('/ai/document-requirements', {
    company_name: input.companyName,
    job_title: input.jobTitle,
    job_description: input.jobDescription,
  })
}

export async function analyzeCompanyIntelligence(input: {
  companyName: string
  jobTitle: string
  jobDescription?: string
}): Promise<AiCompanyIntelligenceResult> {
  return apiClient.post<AiCompanyIntelligenceResult>('/ai/company-intelligence', {
    company_name: input.companyName,
    job_title: input.jobTitle,
    job_description: input.jobDescription,
  })
}

export async function analyzeCredentialMatch(input: {
  jobTitle: string
  jobDescription: string
}): Promise<AiCredentialMatchResult> {
  return apiClient.post<AiCredentialMatchResult>('/ai/credential-match', {
    job_title: input.jobTitle,
    job_description: input.jobDescription,
  })
}

/** Demo-only control: mutates a credential's live cgpa to simulate tampering. */
export async function setCredentialCgpaForDemo(credentialId: string, newCgpa: number): Promise<void> {
  await delay(100)
  const cred = credentials.find((c) => c.id === credentialId)
  if (cred) cred.cgpa = newCgpa
}

export async function resetCredentialCgpaForDemo(credentialId: string): Promise<void> {
  await delay(100)
  const cred = credentials.find((c) => c.id === credentialId)
  if (cred && cred.originalCgpa !== undefined) cred.cgpa = cred.originalCgpa
}

// ---- Student -> institution certificate requests (real backend, PS3 Phase C) ----------

export async function createCertificateRequest(input: {
  institutionId: string
  credentialType: CredentialType
  customCredentialName?: string
  reason?: string
}): Promise<InstitutionCertificateRequest> {
  return apiClient.post<InstitutionCertificateRequest>('/students/me/certificate-requests', {
    institution_id: input.institutionId,
    credential_type: input.credentialType,
    custom_credential_name: input.customCredentialName,
    reason: input.reason,
  })
}

export async function getMyCertificateRequests(): Promise<InstitutionCertificateRequest[]> {
  return apiClient.get<InstitutionCertificateRequest[]>('/students/me/certificate-requests')
}

/** Requests several document types from the institution in one submission — each becomes its own real request row sharing a batch_id, with its own independent PENDING/APPROVED/REJECTED/FULFILLED lifecycle. */
export async function createCertificateRequestBatch(input: {
  institutionId: string
  items: { credentialType: CredentialType; customCredentialName?: string }[]
  reason?: string
}): Promise<InstitutionCertificateRequest[]> {
  return apiClient.post<InstitutionCertificateRequest[]>('/students/me/certificate-requests/batch', {
    institution_id: input.institutionId,
    items: input.items.map((i) => ({ credential_type: i.credentialType, custom_credential_name: i.customCredentialName })),
    reason: input.reason,
  })
}

export async function getInstitutionCertificateRequests(): Promise<InstitutionCertificateRequest[]> {
  return apiClient.get<InstitutionCertificateRequest[]>('/institutions/me/certificate-requests')
}

export async function approveCertificateRequest(requestId: string): Promise<InstitutionCertificateRequest> {
  return apiClient.post<InstitutionCertificateRequest>(`/institutions/me/certificate-requests/${requestId}/approve`)
}

export async function rejectCertificateRequest(requestId: string, reason: string): Promise<InstitutionCertificateRequest> {
  return apiClient.post<InstitutionCertificateRequest>(`/institutions/me/certificate-requests/${requestId}/reject`, { reason })
}

// ---- Student-uploaded existing documents (real backend, PS3 Phase D) ------------------

export async function uploadStudentDocument(input: {
  institutionId: string
  credentialType: CredentialType
  customCredentialName?: string
  document: File
}): Promise<StudentDocument> {
  const form = new FormData()
  form.append('institution_id', input.institutionId)
  form.append('credential_type', input.credentialType)
  if (input.customCredentialName) form.append('custom_credential_name', input.customCredentialName)
  form.append('document', input.document)
  return apiClient.postForm<StudentDocument>('/students/me/documents', form)
}

export async function getMyDocuments(): Promise<StudentDocument[]> {
  return apiClient.get<StudentDocument[]>('/students/me/documents')
}

export async function getInstitutionDocuments(): Promise<StudentDocument[]> {
  return apiClient.get<StudentDocument[]>('/institutions/me/documents')
}

export async function getInstitutionDocument(documentId: string): Promise<StudentDocument> {
  return apiClient.get<StudentDocument>(`/institutions/me/documents/${documentId}`)
}

/** Authenticated fetch of a student-uploaded document's raw PDF bytes — same auth-header pattern as getCredentialDocument. */
export async function getInstitutionDocumentFile(documentId: string): Promise<Blob> {
  return apiClient.getBlob(`/institutions/me/documents/${documentId}/file`)
}

/**
 * A StudentDocument has no structured degree/graduation_year/cgpa fields of
 * its own — it's just an uploaded file. Whatever the institution reviewer
 * confirms while looking at the actual PDF is what carries forward into the
 * resulting signed Credential's real, structured metadata (never inferred
 * from the file, never fabricated).
 */
export async function approveStudentDocument(
  documentId: string,
  academicDetails?: { degree?: string; graduationYear?: number; cgpa?: number }
): Promise<StudentDocument> {
  return apiClient.post<StudentDocument>(`/institutions/me/documents/${documentId}/approve`, {
    degree: academicDetails?.degree || undefined,
    graduation_year: academicDetails?.graduationYear,
    cgpa: academicDetails?.cgpa,
  })
}

export async function rejectStudentDocument(documentId: string, reason: string): Promise<StudentDocument> {
  return apiClient.post<StudentDocument>(`/institutions/me/documents/${documentId}/reject`, { reason })
}

// ---- Real notification counts (real backend, PS3 Phase E) -----------------------------

export async function getNotificationCounts(): Promise<NotificationCounts> {
  return apiClient.get<NotificationCounts>('/notifications/me/counts')
}

// ---- Notification center (real backend) — answers "what new events do I have?",
// distinct from the pending-action counts above ("what currently needs my action?"). ------

/** Paginated, newest-first notification history — never loads the full history in one response. */
export async function getNotificationsPage(params?: { page?: number; pageSize?: number }): Promise<Page<AppNotification>> {
  return apiClient.get<Page<AppNotification>>(
    `/notifications/me${toQueryString({ page: params?.page, page_size: params?.pageSize })}`
  )
}

export async function getUnreadNotificationCount(): Promise<number> {
  return apiClient.get<number>('/notifications/me/unread-count')
}

export async function markNotificationRead(notificationId: string): Promise<AppNotification> {
  return apiClient.post<AppNotification>(`/notifications/me/${notificationId}/read`)
}

export async function markAllNotificationsRead(): Promise<{ updated: number }> {
  return apiClient.post<{ updated: number }>('/notifications/me/read-all')
}

// ---- Verifier document view/download (real backend, PS3 Phase G) ---------------------

/** Any active share grant (any permission level) allows this — backend-enforced. */
export async function viewSharedCredentialDocument(credentialId: string): Promise<Blob> {
  return apiClient.getBlob(`/verification/credentials/${credentialId}/view`)
}

/** Requires the grant's permission to be view_download — backend returns 403 otherwise, enforced server-side regardless of what the UI shows. */
export async function downloadSharedCredentialDocument(credentialId: string): Promise<Blob> {
  return apiClient.getBlob(`/verification/credentials/${credentialId}/download`)
}

// ---- Company profiles (real backend, job marketplace phase) ---------------------------

/** Unwrapped to a plain array — used by the direct-share company picker (ShareFlow.tsx) and anywhere else that predates pagination. See getCompaniesPage for the real paginated directory query. */
export async function getRealCompanies(filters?: { search?: string; industry?: string; location?: string }): Promise<Company[]> {
  const page = await apiClient.get<Page<Company>>(`/companies${toQueryString({ ...filters, page_size: LEGACY_FULL_LIST_PAGE_SIZE })}`)
  return page.items
}

/** One page of the company directory, with the real total/page_count for pagination controls. */
export async function getCompaniesPage(params?: {
  search?: string
  industry?: string
  location?: string
  country?: string
  page?: number
  pageSize?: number
}): Promise<Page<Company>> {
  return apiClient.get<Page<Company>>(
    `/companies${toQueryString({
      search: params?.search,
      industry: params?.industry,
      location: params?.location,
      country: params?.country,
      page: params?.page,
      page_size: params?.pageSize,
    })}`
  )
}

export async function getRealCompany(id: string): Promise<Company> {
  return apiClient.get<Company>(`/companies/${id}`)
}

export async function getMyCompanyProfile(): Promise<Company> {
  return apiClient.get<Company>('/companies/me')
}

export async function updateMyCompanyProfile(input: UpdateCompanyProfileInput): Promise<Company> {
  return apiClient.patch<Company>('/companies/me', input)
}

// ---- Job postings (real backend) -------------------------------------------------------

export async function createJob(input: CreateJobInput): Promise<Job> {
  return apiClient.post<Job>('/companies/me/jobs', input)
}

export async function updateJob(jobId: string, input: Partial<CreateJobInput>): Promise<Job> {
  return apiClient.patch<Job>(`/companies/me/jobs/${jobId}`, input)
}

export async function publishJob(jobId: string): Promise<Job> {
  return apiClient.post<Job>(`/companies/me/jobs/${jobId}/publish`)
}

export async function closeJob(jobId: string): Promise<Job> {
  return apiClient.post<Job>(`/companies/me/jobs/${jobId}/close`)
}

export async function getMyJobs(): Promise<Job[]> {
  return apiClient.get<Job[]>('/companies/me/jobs')
}

/**
 * Public — real open jobs, unwrapped to a plain array. Used by CompanyDetail's "jobs at this
 * company" list and the student Dashboard's job preview — both predate pagination and just want
 * "the list" (see getOpenJobsPage for the real paginated Jobs directory query the student Jobs
 * page uses). GET /api/jobs is paginated server-side (Phase A) exactly like institutions/
 * companies already are; this wrapper absorbs that the same way getInstitutions() does.
 */
export async function getOpenJobs(filters?: { search?: string; companyId?: string; location?: string; degree?: string }): Promise<Job[]> {
  const page = await apiClient.get<Page<Job>>(
    `/jobs${toQueryString({
      search: filters?.search,
      company_id: filters?.companyId,
      location: filters?.location,
      degree: filters?.degree,
      page_size: LEGACY_FULL_LIST_PAGE_SIZE,
    })}`
  )
  return page.items
}

export async function getOpenJobsPage(params?: {
  search?: string
  companyId?: string
  location?: string
  degree?: string
  page?: number
  pageSize?: number
}): Promise<Page<Job>> {
  return apiClient.get<Page<Job>>(
    `/jobs${toQueryString({
      search: params?.search,
      company_id: params?.companyId,
      location: params?.location,
      degree: params?.degree,
      page: params?.page,
      page_size: params?.pageSize,
    })}`
  )
}

export async function getJob(jobId: string): Promise<Job> {
  return apiClient.get<Job>(`/jobs/${jobId}`)
}

// ---- AI job analysis — real job_id driven, reuses the existing AI service --------------

export async function analyzeJobWithAI(jobId: string): Promise<JobAIAnalysisResult> {
  return apiClient.post<JobAIAnalysisResult>(`/ai/analyze-job/${jobId}`)
}

// ---- Job applications -------------------------------------------------------------------

export async function applyToJob(jobId: string, credentialIds: string[]): Promise<StudentJobApplication> {
  return apiClient.post<StudentJobApplication>('/students/me/applications', { job_id: jobId, credential_ids: credentialIds })
}

export async function getMyJobApplications(): Promise<StudentJobApplication[]> {
  return apiClient.get<StudentJobApplication[]>('/students/me/applications')
}

export async function getCompanyApplications(): Promise<CompanyJobApplication[]> {
  return apiClient.get<CompanyJobApplication[]>('/companies/me/applications')
}

export async function updateApplicationStatus(applicationId: string, newStatus: string, reason?: string): Promise<CompanyJobApplication> {
  return apiClient.post<CompanyJobApplication>(`/companies/me/applications/${applicationId}/status`, { status: newStatus, reason })
}

/** Student withdraws their own application — only allowed from a non-final state (not ACCEPTED/REJECTED/already-WITHDRAWN). */
export async function withdrawApplication(applicationId: string): Promise<StudentJobApplication> {
  return apiClient.post<StudentJobApplication>(`/students/me/applications/${applicationId}/withdraw`)
}

// ---- Admin: institution/company verification (Phase A) ----------------------------------
// Every one of these requires role=admin server-side (require_admin) — nothing here is a
// security boundary, it's just the typed client for endpoints only an admin token can succeed
// against. See backend/app/routes/admin.py.

export async function getPendingInstitutions(params?: { search?: string; page?: number; pageSize?: number }): Promise<Page<PendingInstitution>> {
  return apiClient.get<Page<PendingInstitution>>(
    `/admin/institutions/pending${toQueryString({ search: params?.search, page: params?.page, page_size: params?.pageSize })}`
  )
}

export async function approveInstitutionVerification(institutionId: string): Promise<PendingInstitution> {
  return apiClient.post<PendingInstitution>(`/admin/institutions/${institutionId}/approve`)
}

export async function rejectInstitutionVerification(institutionId: string, reason: string): Promise<PendingInstitution> {
  return apiClient.post<PendingInstitution>(`/admin/institutions/${institutionId}/reject`, { reason })
}

export async function getPendingCompanies(params?: { search?: string; page?: number; pageSize?: number }): Promise<Page<PendingCompany>> {
  return apiClient.get<Page<PendingCompany>>(
    `/admin/companies/pending${toQueryString({ search: params?.search, page: params?.page, page_size: params?.pageSize })}`
  )
}

export async function approveCompanyVerification(companyId: string): Promise<PendingCompany> {
  return apiClient.post<PendingCompany>(`/admin/companies/${companyId}/approve`)
}

export async function rejectCompanyVerification(companyId: string, reason: string): Promise<PendingCompany> {
  return apiClient.post<PendingCompany>(`/admin/companies/${companyId}/reject`, { reason })
}
