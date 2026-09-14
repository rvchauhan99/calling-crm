import { useCallback, useMemo } from "react"
import { clampPageSize, DEFAULT_PAGE_SIZE } from "@/components/TablePagination"

/** Read/write `page` and `page_size` from URL search params. */
export function usePageParams(params, setParams, { defaultPageSize = DEFAULT_PAGE_SIZE } = {}) {
  const page = Math.max(1, Number(params.get("page") || 1) || 1)
  const pageSize = useMemo(
    () => clampPageSize(params.get("page_size"), undefined, defaultPageSize),
    [params, defaultPageSize],
  )

  const setPage = useCallback((nextPage) => {
    const p = new URLSearchParams(params)
    const n = Math.max(1, Number(nextPage) || 1)
    if (n <= 1) p.delete("page")
    else p.set("page", String(n))
    setParams(p)
  }, [params, setParams])

  const setPageSize = useCallback((nextSize) => {
    const size = clampPageSize(nextSize, undefined, defaultPageSize)
    const p = new URLSearchParams(params)
    if (size === defaultPageSize) p.delete("page_size")
    else p.set("page_size", String(size))
    p.set("page", "1")
    setParams(p)
  }, [params, setParams, defaultPageSize])

  return { page, pageSize, setPage, setPageSize }
}
