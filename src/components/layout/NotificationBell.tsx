import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Bell, CheckCheck } from 'lucide-react'
import { getNotificationsPage, getUnreadNotificationCount, markNotificationRead, markAllNotificationsRead } from '../../lib/api'
import { notificationLink, relativeTime, cx } from '../../lib/utils'
import type { AppNotification, Role } from '../../types'

const DROPDOWN_PAGE_SIZE = 6

/**
 * The notification bell — "what new events do I have?", distinct from the
 * existing per-nav-item pending-action badges (AppShell.tsx's
 * getNotificationCounts, "what currently needs my action?"). Both stay;
 * this is a separate, additive control, not a replacement.
 *
 * Refreshes the unread count on mount and on navigation (same trigger
 * AppShell already uses for its own badges) — never a polling interval, per
 * the notification design's explicit "no background loop" requirement.
 */
export function NotificationBell({ role }: { role: Role }) {
  const navigate = useNavigate()
  const location = useLocation()
  const [open, setOpen] = useState(false)
  const [unreadCount, setUnreadCount] = useState(0)
  const [notifications, setNotifications] = useState<AppNotification[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    getUnreadNotificationCount()
      .then(setUnreadCount)
      .catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname])

  useEffect(() => {
    if (!open) return
    setLoading(true)
    setError(null)
    getNotificationsPage({ page: 1, pageSize: DROPDOWN_PAGE_SIZE })
      .then((page) => setNotifications(page.items))
      .catch((err) => setError(err instanceof Error ? err.message : 'Could not load notifications.'))
      .finally(() => setLoading(false))
  }, [open])

  useEffect(() => {
    if (!open) return
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setOpen(false)
    }
    function handleEscape(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', handleClickOutside)
    document.addEventListener('keydown', handleEscape)
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('keydown', handleEscape)
    }
  }, [open])

  async function handleOpenNotification(n: AppNotification) {
    setOpen(false)
    if (!n.is_read) {
      setUnreadCount((c) => Math.max(0, c - 1))
      markNotificationRead(n.id).catch(() => {})
    }
    const link = notificationLink(role, n.link_entity_type, n.link_entity_id)
    if (link) navigate(link)
  }

  async function handleMarkAllRead() {
    setNotifications((prev) => prev.map((n) => ({ ...n, is_read: true })))
    setUnreadCount(0)
    try {
      await markAllNotificationsRead()
    } catch {
      // Best-effort — the next open/navigation refetch will reconcile if this failed silently.
    }
  }

  return (
    <div ref={menuRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="true"
        aria-expanded={open}
        aria-label="Notifications"
        className="relative flex h-9 w-9 items-center justify-center rounded-lg text-muted hover:bg-surface-2 hover:text-ink"
      >
        <Bell className="h-5 w-5" strokeWidth={2} />
        {unreadCount > 0 && (
          <span className="absolute right-1 top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-bold text-white shadow-glow-primary">
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div className="fixed inset-x-3 top-16 z-20 overflow-hidden rounded-lg border border-line-strong bg-surface-2 shadow-2xl shadow-black/60 sm:absolute sm:inset-x-auto sm:right-0 sm:top-[calc(100%+6px)] sm:w-80">
          <div className="flex items-center justify-between border-b border-line px-3.5 py-2.5">
            <p className="text-sm font-semibold text-ink">Notifications</p>
            {unreadCount > 0 && (
              <button
                type="button"
                onClick={handleMarkAllRead}
                className="flex items-center gap-1 text-[11px] font-semibold text-primary hover:underline"
              >
                <CheckCheck className="h-3 w-3" strokeWidth={2.5} />
                Mark all read
              </button>
            )}
          </div>

          <div className="max-h-96 overflow-y-auto">
            {loading ? (
              <p className="px-3.5 py-6 text-center text-[13px] text-muted">Loading…</p>
            ) : error ? (
              <p className="px-3.5 py-6 text-center text-[13px] text-bad">{error}</p>
            ) : notifications.length === 0 ? (
              <p className="px-3.5 py-6 text-center text-[13px] text-muted">You're all caught up.</p>
            ) : (
              notifications.map((n) => (
                <button
                  key={n.id}
                  type="button"
                  onClick={() => handleOpenNotification(n)}
                  className={cx(
                    'flex w-full flex-col gap-0.5 border-b border-line/60 px-3.5 py-2.5 text-left last:border-b-0 hover:bg-surface',
                    !n.is_read && 'bg-primary-bg/40'
                  )}
                >
                  <div className="flex items-center gap-2">
                    {!n.is_read && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />}
                    <p className={cx('truncate text-[13px]', n.is_read ? 'font-medium text-ink' : 'font-bold text-ink')}>{n.title}</p>
                  </div>
                  <p className="truncate text-[12px] text-muted">{n.message}</p>
                  <p className="text-[10px] text-faint">{relativeTime(n.created_at)}</p>
                </button>
              ))
            )}
          </div>

          <button
            type="button"
            onClick={() => {
              setOpen(false)
              navigate(`/${role}/notifications`)
            }}
            className="block w-full border-t border-line px-3.5 py-2.5 text-center text-[12px] font-semibold text-primary hover:bg-surface"
          >
            View all
          </button>
        </div>
      )}
    </div>
  )
}
