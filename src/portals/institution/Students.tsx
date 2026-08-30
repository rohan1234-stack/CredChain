import { useEffect, useState } from 'react'
import { Users, ShieldCheck } from 'lucide-react'
import { getStudents } from '../../lib/api'
import { ApiError } from '../../lib/apiClient'
import { PageHeader, Card, EmptyState, SearchInput } from '../../components/ui'
import { SkeletonCard } from '../../components/ui/Skeleton'
import { InitialsAvatar } from '../../components/ui/IconTile'
import { shortHash } from '../../lib/utils'

/**
 * Reproduces the actual Stitch "institution_student_management" screen: a
 * search bar above a vertical stack of glass cards, each with a circular
 * avatar, name, a mono "ID" line, a verified-status pill, and a bottom
 * credentials-count row (see stitch2/institution_student_management/code.html).
 * Stitch's own screen shows fictional "Alex Mercer" / "Jordan Lee" avatar
 * photos and a fake "LAST SYNC: 2h ago" field with no backend equivalent —
 * neither appears below; the avatar is the real InitialsAvatar already used
 * elsewhere, the ID line is the real student id (truncated, not implying a
 * wallet address), and "Last Sync" is omitted rather than fabricated.
 */
export function Students() {
  const [students, setStudents] = useState<{ id: string; name: string; initials: string; credentialCount: number }[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getStudents()
      .then(setStudents)
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Unable to load students. Please try again.'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="space-y-4"><SkeletonCard lines={3} /><SkeletonCard lines={3} /></div>

  const filtered = students.filter((s) => s.name.toLowerCase().includes(search.trim().toLowerCase()))

  return (
    <div>
      <PageHeader title="Students" eyebrow="Student Directory" icon={Users} description="Manage verified student records affiliated with your institution." />

      {error && <div className="mb-4 max-w-2xl rounded-lg bg-bad-bg px-3.5 py-2.5 text-[13px] text-bad">{error}</div>}

      {students.length > 0 && (
        <div className="mb-5 max-w-2xl">
          <SearchInput value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search by name…" />
        </div>
      )}

      {students.length === 0 ? (
        !error && (
          <EmptyState
            icon={Users}
            title="No students yet"
            description="No students are currently linked to this institution."
          />
        )
      ) : filtered.length === 0 ? (
        <EmptyState icon={Users} title="No matching students" description="Try a different search term." />
      ) : (
        <div className="max-w-2xl space-y-3">
          {filtered.map((s) => (
            <Card key={s.id} className="relative overflow-hidden p-5">
              <div aria-hidden className="absolute right-0 top-0 h-full w-1 bg-gradient-to-b from-primary to-transparent opacity-50" />
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-3">
                  <InitialsAvatar initials={s.initials} tone="primary" />
                  <div>
                    <p className="text-base font-semibold text-ink">{s.name}</p>
                    <p className="mt-0.5 font-[family-name:var(--font-mono)] text-[11px] text-faint">ID: {shortHash(s.id, 8, 4)}</p>
                  </div>
                </div>
                <span className="flex shrink-0 items-center gap-1 rounded-full border border-good-line bg-good-bg px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider text-good">
                  <ShieldCheck className="h-3 w-3" strokeWidth={2.5} /> Affiliated
                </span>
              </div>
              <div className="mt-3 flex items-center gap-1.5 border-t border-line pt-3 text-primary">
                <ShieldCheck className="h-4 w-4" strokeWidth={2} />
                <span className="font-[family-name:var(--font-mono)] text-sm font-bold text-ink">
                  {s.credentialCount} credential{s.credentialCount === 1 ? '' : 's'} issued
                </span>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
