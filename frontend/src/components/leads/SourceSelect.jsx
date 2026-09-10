import { useEffect, useState } from "react"
import { SearchableSelect } from "@/components/ui/searchable-select"
import api from "@/lib/api"

export function SourceSelect({
  value,
  onChange,
  includeImport = false,
  includeAll = false,
  placeholder = "Select source",
  label = "Source",
  testId = "lead-field-source",
  className = "mt-1",
}) {
  const [sourceList, setSourceList] = useState([])

  useEffect(() => {
    let cancelled = false
    api.get("/lead-sources")
      .then((r) => {
        if (cancelled) return
        const rows = (r.data.lead_sources || []).filter((s) => s.active !== false)
        const names = rows
          .filter((s) => includeImport || s.creatable !== false)
          .map((s) => s.name)
          .filter(Boolean)
        setSourceList(names)
      })
      .catch(() => {
        if (!cancelled) setSourceList([])
      })
    return () => { cancelled = true }
  }, [includeImport])

  const options = [
    ...(includeAll ? [{ value: "all", label: "All sources" }] : []),
    ...sourceList.map((s) => ({ value: s, label: s })),
  ]

  return (
    <SearchableSelect
      options={options}
      value={value || undefined}
      onChange={onChange}
      placeholder={placeholder}
      searchPlaceholder="Search sources…"
      label={label}
      testId={testId}
      className={className}
    />
  )
}
