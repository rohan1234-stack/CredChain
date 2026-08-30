import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bell, CheckCheck } from 'lucide-react'
import { getNotificationsPage, markNotificationRead, markAllNotificationsRead } from '../../lib/api'
import { ApiError } from '../../lib/apiClient'
import { notificationLink, relativeTime, cx } from '../../lib/utils'
import { useAuth } from '../../context/AuthContext'
import type { AppNotification } from '../../types'
import { PageHeader, GlassPanel, Button, EmptyState, ErrorState, Pagination } from '../../components/ui'
import { SkeletonRow } from '../../components/ui/Skeleton'

const PAGE_SIZE = 20

/**
 * Full notification history — one shared page reused across every portal
 * (student/institution/verifier/admin all route here; see App.tsx), since
 * the underlying data and actions are identical regardless of role. Only
 * the destination a click navigates to differs, via notificationLink(role, ...).
 */
export function Notifications() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [result, setResult] = useState<{ items: AppNotification[]; total: number; totalPages: number } | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [retryToken, setRetryToken] = useState(0)

  useEffect(() => {
    setLoading(true)
    setError(null)
    getNotificationsPage({ page, pageSize: PAGE_SIZE })
      .then((data) => setResult({ items: data.items, total: data.total, totalPages: data.total_pages }))
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Could not load notifications.'))
      .finally(() => setLoading(false))
  }, [page, retryToken])

  async function handleOpen(n: AppNotification) {
    if (!user) return
    if (!n.is_read) {
      setResult((prev) => prev && { ...prev, items: prev.items.map((x) => (x.id === n.id ? { ...x, is_read: true } : x)) })
      markNotificationRead(n.id).catch(() => {})
    }
    const link = notificationLink(user.role, n.link_entity_type, n.link_entity_id)
    if (link) navigate(link)
  }

  async function handleMarkAllRead() {
    setResult((prev) => prev && { ...prev, items: prev.items.map((n) => ({ ...n, is_read: true })) })
    try {
      await markAllNotificationsRead()
    } catch {
      setRetryToken((t) => t + 1)
    }
  }

  const items = result?.items ?? []
  const hasUnread = items.some((n) => !n.is_read)

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <PageHeader title="Notifications" eyebrow="Activity" icon={Bell} description="Everything relevant to your account, newest first." />
        {hasUnread && (
          <Button variant="outline" size="sm" icon={<CheckCheck className="h-3.5 w-3.5" />} onClick={handleMarkAllRead}>
            Mark all read
          </Button>
        )}
      </div>

      {error ? (
        <ErrorState description={error} onRetry={() => setRetryToken((t) => t + 1)} />
      ) : loading && !result ? (
        <div className="space-y-2.5">
          <SkeletonRow />
          <SkeletonRow />
          <SkeletonRow />
        </div>
      ) : items.length === 0 ? (
        <EmptyState icon={Bell} title="No notifications yet" description="You're all caught up — new activity will show up here." />
      ) : (
        <>
          <div className="space-y-2">
            {items.map((n) => (
              <button key={n.id} type="button" onClick={() => handleOpen(n)} className="block w-full text-left">
                <GlassPanel
                  className={cx('flex items-start gap-3 p-4 transition-colors hover:border-primary-line', !n.is_read && 'bg-primary-bg/30')}
                >
                  {!n.is_read && <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-primary" />}
                  <div className={cx('min-w-0 flex-1', n.is_read && 'pl-5')}>
                    <p className={cx('truncate text-sm', n.is_read ? 'font-medium text-ink' : 'font-bold text-ink')}>{n.title}</p>
                    <p className="mt-0.5 truncate text-[13px] text-muted">{n.message}</p>
                    <p className="mt-1 text-[11px] text-faint">{relativeTime(n.created_at)}</p>
                  </div>
                </GlassPanel>
              </button>
            ))}
          </div>
          {result && <Pagination page={page} totalPages={result.totalPages} total={result.total} onPageChange={setPage} />}
        </>
      )}
    </div>
  )
}
