import { useEffect, useState } from "react"
import { SearchableSelect } from "@/components/ui/searchable-select"
import { inactiveMasterLabel } from "@/lib/masterOptions"
import api from "@/lib/api"

export function SourceSelect({
  value,
  onChange,
  includeImport = false,
  includeAll = false,
  includeInactive = false,
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
        const rows = (r.data.lead_sources || []).filter(
          (s) => includeInactive || s.active !== false,
        )
        const options = rows
          .filter((s) => includeImport || s.creatable !== false)
          .filter((s) => s.name)
          .map((s) => ({
            value: s.name,
            label: inactiveMasterLabel(s.name, s.active),
          }))
        setSourceList(options)
      })
      .catch(() => {
        if (!cancelled) setSourceList([])
      })
    return () => { cancelled = true }
  }, [includeImport, includeInactive])

  const options = [
    ...(includeAll ? [{ value: "all", label: "All sources" }] : []),
    ...sourceList,
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
