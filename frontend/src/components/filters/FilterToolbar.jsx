import { Label } from "@/components/ui/label"
import { cn } from "@/lib/utils"
import { FilterChips } from "@/components/filters/FilterChips"

export const FilterField = ({ label, htmlFor, className, children }) => (
  <div className={cn("shrink-0", className)}>
    {label && (
      <Label htmlFor={htmlFor} className="mb-0.5 block text-[11px] font-medium text-slate-500">
        {label}
      </Label>
    )}
    {children}
  </div>
)

export const FilterToolbar = ({
  search,
  fields,
  sort,
  actions,
  chips,
  onClearAll,
  className,
  testId = "filter-toolbar",
}) => (
  <div className={cn("mb-3 space-y-2", className)} data-testid={testId}>
    <div className="flex flex-wrap items-end gap-x-3 gap-y-2 rounded-lg border border-slate-200 bg-white p-2.5 shadow-sm">
      {search && <div className="relative min-w-[12rem] flex-1">{search}</div>}
      {fields}
      {sort}
      {actions}
    </div>
    {(chips?.length > 0 || onClearAll) && (
      <FilterChips chips={chips} onClearAll={chips?.length ? onClearAll : undefined} />
    )}
  </div>
)
