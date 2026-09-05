import { Button } from "@/components/ui/button"

export const PAGE_SIZE_OPTIONS = [25, 50, 75, 100]
export const DEFAULT_PAGE_SIZE = 25

export function paginationRange(page, pageSize, total) {
  if (total <= 0) return { from: 0, to: 0 }
  const from = (page - 1) * pageSize + 1
  const to = Math.min(page * pageSize, total)
  return { from, to }
}

export function clampPageSize(value, options = PAGE_SIZE_OPTIONS, fallback = DEFAULT_PAGE_SIZE) {
  const n = Number(value)
  if (!Number.isFinite(n) || n <= 0) return fallback
  if (options.includes(n)) return n
  return fallback
}

export function TablePagination({
  page,
  pageSize,
  total,
  onPageChange,
  onPageSizeChange,
  pageSizeOptions = PAGE_SIZE_OPTIONS,
}) {
  if (!total || total <= 0) return null

  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const { from, to } = paginationRange(page, pageSize, total)

  const handlePageSizeChange = (e) => {
    const next = Number(e.target.value)
    onPageSizeChange?.(next)
  }

  return (
    <div
      className="mt-4 flex flex-col gap-3 text-sm text-slate-500 sm:flex-row sm:items-center sm:justify-between"
      data-testid="table-pagination"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="tabular-nums text-slate-700" data-testid="pagination-range">
          {from}–{to} of {total}
        </span>
        {totalPages > 1 && (
          <span className="text-slate-400" data-testid="pagination-page-label">
            Page {page} of {totalPages}
          </span>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2" htmlFor="page-size-select">
          <span className="whitespace-nowrap text-slate-500">Rows per page</span>
          <select
            id="page-size-select"
            value={pageSize}
            onChange={handlePageSizeChange}
            className="h-8 rounded-md border border-slate-200 bg-white px-2 text-sm text-slate-700 focus:outline-none focus:ring-2 focus:ring-sky-500"
            aria-label="Rows per page"
            data-testid="page-size-select"
          >
            {pageSizeOptions.map((size) => (
              <option key={size} value={size}>{size}</option>
            ))}
          </select>
        </label>

        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={page <= 1}
            onClick={() => onPageChange?.(page - 1)}
            data-testid="prev-page"
          >
            Prev
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= totalPages}
            onClick={() => onPageChange?.(page + 1)}
            data-testid="next-page"
          >
            Next
          </Button>
        </div>
      </div>
    </div>
  )
}
