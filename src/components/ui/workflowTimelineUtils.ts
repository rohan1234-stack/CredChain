import type { ApplicationHistoryEntry, ApplicationStatus, InstitutionCertificateRequest } from '../../types'
import type { WorkflowStep } from './WorkflowTimeline'

/**
 * Builds the real workflow steps for one InstitutionCertificateRequest —
 * shared by the student and institution certificate-request pages, since
 * both read the exact same backend fields. Follows the actual state
 * machine (PENDING -> APPROVED -> FULFILLED, or PENDING -> REJECTED) with
 * no invented phases: "Approved" only appears once responded_at is real,
 * "Credential Issued" only completes once fulfilled_at is real, and the
 * REJECTED branch never shows the Approved/Credential Issued steps at all
 * (that branch of the state machine was never reached).
 */
export function buildCertificateRequestSteps(request: InstitutionCertificateRequest): WorkflowStep[] {
  const requested: WorkflowStep = { key: 'requested', label: 'Requested', state: 'completed', occurredAt: request.created_at }

  if (request.status === 'rejected') {
    return [
      requested,
      {
        key: 'rejected',
        label: 'Rejected',
        state: 'rejected',
        occurredAt: request.responded_at,
        description: request.rejection_reason ? `Reason: ${request.rejection_reason}` : undefined,
      },
    ]
  }

  const approved: WorkflowStep =
    request.status === 'pending'
      ? { key: 'approved', label: 'Approved', state: 'current' }
      : { key: 'approved', label: 'Approved', state: 'completed', occurredAt: request.responded_at }

  const issued: WorkflowStep =
    request.status === 'fulfilled'
      ? { key: 'issued', label: 'Credential Issued', state: 'completed', occurredAt: request.fulfilled_at }
      : request.status === 'approved'
        ? { key: 'issued', label: 'Credential Issued', state: 'current' }
        : { key: 'issued', label: 'Credential Issued', state: 'pending' }

  return [requested, approved, issued]
}

const _APPLICATION_STATUS_LABEL: Record<ApplicationStatus, string> = {
  applied: 'Applied',
  under_review: 'Under Review',
  shortlisted: 'Shortlisted',
  accepted: 'Accepted',
  rejected: 'Rejected',
  withdrawn: 'Withdrawn',
}

// The one assumed forward ("happy") path used only to render dimmed, not-yet-reached
// placeholders after the current non-terminal status — never used to fabricate a completed
// step or a timestamp. REJECTED is reachable from every one of these but is deliberately never
// shown as a speculative future step; it only ever appears once it has actually happened.
const _HAPPY_PATH: ApplicationStatus[] = ['applied', 'under_review', 'shortlisted', 'accepted']

const _TERMINAL_STATUSES: ApplicationStatus[] = ['accepted', 'rejected', 'withdrawn']

/**
 * Builds the real workflow steps for one job application — shared by the
 * student and company application pages. Every completed/current step
 * comes directly from a real ActivityLog-backed `history` entry (see
 * job_application_service.get_application_history); nothing here derives a
 * status or a timestamp from updated_at or a notification. Any step that
 * hasn't been reached yet is rendered `pending` with no timestamp at all.
 */
export function buildJobApplicationSteps(
  history: ApplicationHistoryEntry[],
  status: ApplicationStatus,
  rejectionReason: string | null
): WorkflowStep[] {
  // Defensive fallback only — APPLICATION_SUBMITTED is always logged at creation, so this
  // should never actually be empty, but a real applied_at is still preferable to nothing.
  const entries = history.length > 0 ? history : [{ status: 'applied' as ApplicationStatus, occurred_at: '' }]

  const steps: WorkflowStep[] = entries.map((entry, i) => {
    const isLastEntry = i === entries.length - 1
    const label = _APPLICATION_STATUS_LABEL[entry.status]

    if (entry.status === 'rejected') {
      return {
        key: `history-${i}`,
        label,
        state: 'rejected',
        occurredAt: entry.occurred_at || null,
        description: rejectionReason ? `Reason: ${rejectionReason}` : undefined,
      }
    }
    if (entry.status === 'withdrawn') {
      return { key: `history-${i}`, label, state: 'rejected', occurredAt: entry.occurred_at || null }
    }
    // The most recent entry, when it's not itself a terminal outcome, IS the current live
    // status — shown as "in progress" rather than a past timestamp, even though a real one
    // exists in `history`, to make clear this is where the application stands right now.
    if (isLastEntry && !_TERMINAL_STATUSES.includes(status)) {
      return { key: `history-${i}`, label, state: 'current' }
    }
    return { key: `history-${i}`, label, state: 'completed', occurredAt: entry.occurred_at || null }
  })

  if (_TERMINAL_STATUSES.includes(status)) {
    return steps
  }

  // Non-terminal: append dimmed placeholders for the remaining happy-path stages not yet
  // reached, stopping at ACCEPTED — never a speculative REJECTED/WITHDRAWN placeholder.
  const reachedIndex = _HAPPY_PATH.indexOf(status)
  const remaining = reachedIndex === -1 ? [] : _HAPPY_PATH.slice(reachedIndex + 1)
  for (const futureStatus of remaining) {
    steps.push({ key: `pending-${futureStatus}`, label: _APPLICATION_STATUS_LABEL[futureStatus], state: 'pending' })
  }

  return steps
}
