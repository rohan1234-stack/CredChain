import { useEffect, useState } from 'react'
import { Activity as ActivityIcon } from 'lucide-react'
import { getActivity } from '../../lib/api'
import { ApiError } from '../../lib/apiClient'
import type { AccessLogEntry } from '../../types'
import { PageHeader, FilterPills, EmptyState, ErrorState, GlassPanel } from '../../components/ui'
import { SkeletonCard } from '../../components/ui/Skeleton'
import { cx, TONE_CLASSES, TONE_GRADIENT_FROM, ACTIVITY_ICON_MAP, ACTIVITY_FILTER_OPTIONS } from '../../lib/utils'

/**
 * Reproduces Stitch's "activity_log" screen: a connected vertical timeline
 * where each event is its own glass card with a colored left-streak and an
 * uppercase status chip + mono timestamp header. Stitch's own screen pads
 * each card with a fabricated technical detail box (fake tx hash, gas used,
 * a fake issuer DID) — the real AccessLogEntry this app has carries no such
 * fields, so that box is omitted entirely rather than inventing values;
 * every card below shows only the real action/actor/timestamp already
 * returned by getActivity().
 */

type Filter = AccessLogEntry['category'] | 'all'

function isToday(entry: AccessLogEntry) {
  return entry.timestamp.includes('AM') || entry.timestamp.includes('PM') || entry.timestamp === 'Just now'
}

function EventCard({ entry, last }: { entry: AccessLogEntry; last: boolean }) {
  const { icon: Icon, tone: toneKey } = ACTIVITY_ICON_MAP[entry.icon]
  const tone = TONE_CLASSES[toneKey]
  return (
    <div className="relative flex gap-4">
      <div className="flex flex-col items-center">
        <div className={cx('z-10 flex h-9 w-9 shrink-0 items-center justify-center rounded-full border', tone.border, tone.bg)}>
          <Icon className={cx('h-4 w-4', tone.text)} strokeWidth={2.25} />
        </div>
        {!last && <span aria-hidden className="mt-1 w-px flex-1 bg-line" />}
      </div>
      <GlassPanel className="relative mb-5 flex-1 overflow-hidden p-4">
        <div aria-hidden className={cx('absolute inset-y-0 left-0 w-1 bg-gradient-to-b', TONE_GRADIENT_FROM[toneKey], 'to-transparent')} />
        <div className="flex items-center justify-between gap-3 pl-2">
          <span className={cx('rounded border px-2 py-0.5 font-[family-name:var(--font-mono)] text-[10px] font-semibold uppercase tracking-wider', tone.border, tone.bg, tone.text)}>
            {entry.label}
          </span>
          <span className="font-[family-name:var(--font-mono)] text-[11px] text-faint">{entry.timestamp}</span>
        </div>
        <p className="mt-2 pl-2 text-sm font-semibold text-ink">{entry.action}</p>
        <p className="pl-2 text-[12px] text-muted">{entry.actor}</p>
      </GlassPanel>
    </div>
  )
}

export function Activity() {
  const [log, setLog] = useState<AccessLogEntry[]>([])
  const [filter, setFilter] = useState<Filter>('all')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getActivity()
      .then(setLog)
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Could not load activity. Please try again.'))
      .finally(() => setLoading(false))
  }, [])

  const filtered = log.filter((l) => filter === 'all' || l.category === filter)
  const today = filtered.filter(isToday)
  const earlier = filtered.filter((l) => !isToday(l))
  const ordered = [...today, ...earlier]

  return (
    <div>
      <PageHeader
        title="Activity Audit Trail"
        eyebrow="Audit Trail"
        icon={ActivityIcon}
        description="Immutable record of who accessed what, and when."
      />

      {error && <div className="mb-5 max-w-2xl"><ErrorState description={error} onRetry={() => window.location.reload()} /></div>}

      <FilterPills value={filter} onChange={setFilter} options={ACTIVITY_FILTER_OPTIONS} />

      <div className="mt-6 max-w-2xl">
        {loading ? (
          <SkeletonCard lines={4} />
        ) : filtered.length === 0 ? (
          <EmptyState icon={ActivityIcon} title="No activity yet" description="Sharing, verification and request events will show up here." />
        ) : (
          <div>
            {today.length > 0 && (
              <p className="mb-3 text-[10px] font-bold uppercase tracking-wider text-faint">Today</p>
            )}
            {ordered.map((entry, i) => (
              <EventCard key={entry.id} entry={entry} last={i === ordered.length - 1} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
