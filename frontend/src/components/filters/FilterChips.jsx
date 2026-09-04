import { Button } from "@/components/ui/button"
import { FilterChip } from "@/components/dashboard/atoms"

export const FilterChips = ({ chips = [], onClearAll, testId = "filter-chips" }) => {
  if (!chips.length) return null
  return (
    <div className="flex flex-wrap items-center gap-1.5" data-testid={testId}>
      {chips.map((c) => (
        <FilterChip key={c.key} label={c.label} onRemove={c.onRemove} />
      ))}
      {onClearAll && (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-7 px-2 text-xs text-slate-500"
          onClick={onClearAll}
          data-testid="clear-all-filters"
        >
          Clear all
        </Button>
      )}
    </div>
  )
}
