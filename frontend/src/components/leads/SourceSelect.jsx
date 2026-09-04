import { SearchableSelect } from "@/components/ui/searchable-select"
import { LEAD_SOURCES, LEAD_SOURCES_CREATABLE } from "@/constants/leadSources"

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
  const sourceList = includeImport ? LEAD_SOURCES : LEAD_SOURCES_CREATABLE
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
