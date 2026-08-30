import { ChevronLeft, ChevronRight } from 'lucide-react'
import { Button } from './Button'

/**
 * Page-by-page navigation for a backend-paginated list (institution/company
 * directory — see Page<T> in types.ts). Deliberately simple: prev/next +
 * "Page X of Y" + a real result count, no jump-to-page input — a directory
 * that can scale to tens of thousands of rows is browsed by
 * searching/filtering down to a small result set, not by paging through it.
 */
export function Pagination({
  page,
  totalPages,
  total,
  onPageChange,
}: {
  page: number
  totalPages: number
  total: number
  onPageChange: (page: number) => void
}) {
  if (total === 0) return null

  return (
    <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-white/5 pt-4">
      <p className="text-[12px] text-muted">
        {total.toLocaleString()} result{total === 1 ? '' : 's'} — page {page} of {totalPages}
      </p>
      <div className="flex items-center gap-2">
        <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => onPageChange(page - 1)} icon={<ChevronLeft className="h-3.5 w-3.5" />}>
          Previous
        </Button>
        <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => onPageChange(page + 1)}>
          Next
          <ChevronRight className="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>
  )
}
