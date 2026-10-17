import { useMemo } from "react"
import { getCountries, getCountryCallingCode } from "libphonenumber-js"
import { SearchableSelect } from "@/components/ui/searchable-select"
import { FilterField } from "@/components/filters/FilterToolbar"

function buildCountryOptions(includeAll) {
  const rows = getCountries()
    .map((code) => ({
      value: code,
      label: `${code} +${getCountryCallingCode(code)}`,
    }))
    .sort((a, b) => a.label.localeCompare(b.label))
  if (includeAll) return [{ value: "all", label: "All countries" }, ...rows]
  return rows
}

const FILTER_OPTIONS = buildCountryOptions(true)
const PHONE_OPTIONS = buildCountryOptions(false)

export function CountryFilter({ value, onChange, testId = "country-filter" }) {
  return (
    <FilterField label="Country" className="w-40">
      <SearchableSelect
        value={value || "all"}
        onChange={(v) => onChange(v === "all" ? "" : v)}
        options={FILTER_OPTIONS}
        placeholder="All countries"
        testId={testId}
        className="h-8"
      />
    </FilterField>
  )
}

export function PhoneCountrySelect({ value = "IN", onChange, testId = "phone-country" }) {
  const options = useMemo(() => PHONE_OPTIONS, [])
  return (
    <SearchableSelect
      value={value || "IN"}
      onChange={onChange}
      options={options}
      placeholder="Country"
      testId={testId}
      className="h-9 w-[7.5rem]"
    />
  )
}
