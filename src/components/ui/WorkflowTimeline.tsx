import { Check, Circle, X } from 'lucide-react'
import { cx, formatTimelineTimestamp } from '../../lib/utils'

export type WorkflowStepState = 'completed' | 'current' | 'pending' | 'rejected'

export interface WorkflowStep {
  /** Stable identity for the React key — not displayed. */
  key: string
  label: string
  state: WorkflowStepState
  /**
   * Real ISO timestamp for this step, or null/undefined if this step hasn't
   * genuinely happened yet. Only 'completed' and 'rejected' steps should
   * ever carry one — never fabricate a time for 'current'/'pending'.
   */
  occurredAt?: string | null
  /** Optional extra line — e.g. a real rejection reason. Never fabricated copy. */
  description?: string
}

const STATE_STYLES: Record<WorkflowStepState, { icon: typeof Check; iconClass: string; ringClass: string; labelClass: string; subtitleClass: string }> = {
  completed: {
    icon: Check,
    iconClass: 'border-good-line bg-good-bg text-good',
    ringClass: 'shadow-glow-good',
    labelClass: 'text-ink',
    subtitleClass: 'text-faint',
  },
  current: {
    icon: Circle,
    iconClass: 'border-primary-line bg-primary-bg text-primary',
    ringClass: 'shadow-glow-primary',
    labelClass: 'text-ink',
    subtitleClass: 'text-primary',
  },
  pending: {
    icon: Circle,
    iconClass: 'border-line bg-canvas-2 text-faint',
    ringClass: '',
    labelClass: 'text-faint',
    subtitleClass: 'text-faint',
  },
  rejected: {
    icon: X,
    iconClass: 'border-bad-line bg-bad-bg text-bad',
    ringClass: 'shadow-glow-bad',
    labelClass: 'text-ink',
    subtitleClass: 'text-bad',
  },
}

const STATE_ARIA_PREFIX: Record<WorkflowStepState, string> = {
  completed: 'Completed:',
  current: 'Current step:',
  pending: 'Not yet reached:',
  rejected: 'Rejected:',
}

function subtitleFor(step: WorkflowStep): string {
  if (step.occurredAt) return formatTimelineTimestamp(step.occurredAt)
  if (step.state === 'current') return 'In progress'
  if (step.state === 'pending') return 'Not yet reached'
  return ''
}

/**
 * Real-data-only workflow status timeline — completed / current / pending /
 * rejected steps for a credential request or job application. Reuses the
 * same visual language (connecting line, tone-colored circular icon
 * markers) as the existing Timeline/TimelineItem used on the Activity
 * feed, but adds the 'current' (in progress, no timestamp) and 'pending'
 * (dimmed, "Not yet reached") states a flat historical feed never needed.
 *
 * Never fabricates a step or a timestamp: callers must only pass steps the
 * backend's real state machine + recorded history actually support, and a
 * step's `occurredAt` must be omitted (not guessed) when no real event
 * timestamp exists yet.
 */
export function WorkflowTimeline({ steps }: { steps: WorkflowStep[] }) {
  return (
    <ol className="relative">
      {steps.map((step, i) => {
        const isLast = i === steps.length - 1
        const styles = STATE_STYLES[step.state]
        const Icon = styles.icon
        const subtitle = subtitleFor(step)
        return (
          <li key={step.key} className="relative flex gap-3 pb-5 last:pb-0">
            {!isLast && <span aria-hidden className="absolute left-[13px] top-7 bottom-0 w-px bg-line" />}
            <div
              className={cx(
                'z-10 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border',
                styles.iconClass,
                styles.ringClass
              )}
              aria-hidden
            >
              <Icon className={cx('h-3.5 w-3.5', step.state === 'current' && 'fill-current')} strokeWidth={2.5} />
            </div>
            <div className="min-w-0 flex-1 pt-0.5">
              <p className={cx('text-sm font-semibold', styles.labelClass)}>
                <span className="sr-only">{STATE_ARIA_PREFIX[step.state]} </span>
                {step.label}
              </p>
              {subtitle && <p className={cx('mt-0.5 text-xs', styles.subtitleClass)}>{subtitle}</p>}
              {step.description && <p className="mt-1 text-xs text-muted">{step.description}</p>}
            </div>
          </li>
        )
      })}
    </ol>
  )
}
