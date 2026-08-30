import { useEffect, useRef, useState } from 'react'
import { ChevronDown, LogOut, Menu } from 'lucide-react'
import { InitialsAvatar } from '../ui/IconTile'
import { useAuth } from '../../context/AuthContext'
import { NotificationBell } from './NotificationBell'
import type { User, Role } from '../../types'

const ROLE_LABEL: Record<Role, string> = {
  student: 'Student',
  institution: 'Institution',
  verifier: 'Company',
  admin: 'Admin',
}

export function TopBar({ user, onMenuClick }: { user: User; onMenuClick?: () => void }) {
  const { logout } = useAuth()
  const [open, setOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

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

  function handleLogout() {
    logout()
    // Full browser navigation, not client-side routing: guarantees landing
    // on "/" deterministically instead of racing ProtectedRoute's own
    // redirect-to-/sign-in effect (which fires when the current protected
    // route re-renders with user now null).
    window.location.href = '/'
  }

  return (
    <header className="relative z-10 flex h-16 shrink-0 items-center gap-4 border-b border-line glass-surface px-4 sm:px-6">
      <button
        type="button"
        onClick={onMenuClick}
        aria-label="Open navigation"
        className="rounded-lg p-1.5 text-muted hover:bg-surface-2 hover:text-ink lg:hidden"
      >
        <Menu className="h-5 w-5" strokeWidth={2} />
      </button>
      <div className="ml-auto flex items-center gap-3">
        <NotificationBell role={user.role} />
        <div ref={menuRef} className="relative">
          <button
            onClick={() => setOpen((v) => !v)}
            aria-haspopup="true"
            aria-expanded={open}
            className="flex cursor-pointer items-center gap-2 rounded-lg py-1 pl-1 pr-2 hover:bg-surface-2"
          >
            <InitialsAvatar initials={user.initials} tone="primary" size="sm" />
            <span className="flex flex-col items-start leading-tight">
              <span className="text-sm font-semibold text-ink">{user.name}</span>
              <span className="text-[11px] text-faint">{ROLE_LABEL[user.role]}</span>
            </span>
            <ChevronDown className="h-4 w-4 text-faint" strokeWidth={2} />
          </button>

          {open && (
            <div className="absolute right-0 top-[calc(100%+6px)] z-20 w-52 overflow-hidden rounded-lg border border-line-strong bg-surface-2 shadow-2xl shadow-black/60">
              <div className="px-3.5 py-3">
                <p className="truncate text-sm font-semibold text-ink">{user.name}</p>
                <p className="text-xs text-faint">{ROLE_LABEL[user.role]}</p>
              </div>
              <div className="border-t border-line">
                <button
                  onClick={handleLogout}
                  className="flex w-full items-center gap-2 px-3.5 py-2.5 text-left text-sm font-medium text-bad hover:bg-bad-bg"
                >
                  <LogOut className="h-4 w-4" strokeWidth={2} />
                  Sign out
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}
