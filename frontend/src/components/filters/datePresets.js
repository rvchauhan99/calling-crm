import {
  monthStartISO,
  todayISO,
  startOfWeekISO,
  monthsAgoISO,
} from "@/components/dashboard/atoms"

export const DATE_PRESETS = [
  { id: "today", label: "Today", apply: () => ({ from: todayISO(), to: todayISO() }) },
  { id: "week", label: "This Week", apply: () => ({ from: startOfWeekISO(), to: todayISO() }) },
  { id: "month", label: "This Month", apply: () => ({ from: monthStartISO(), to: todayISO() }) },
  { id: "3m", label: "Last 3M", apply: () => ({ from: monthsAgoISO(3), to: todayISO() }) },
]

/**
 * Return preset id when from/to match a known range, else "".
 * When multiple presets share the same range (e.g. Today === This Week on Monday),
 * prefer preferredId if it is among the matches.
 */
export const matchDatePresetId = (from, to, preferredId = "") => {
  if (!from || !to) return ""
  const matches = DATE_PRESETS.filter((preset) => {
    const range = preset.apply()
    return range.from === from && range.to === to
  })
  if (!matches.length) return ""
  if (preferredId && matches.some((m) => m.id === preferredId)) return preferredId
  return matches[0].id
}
