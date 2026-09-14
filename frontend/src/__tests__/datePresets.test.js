import { DATE_PRESETS, matchDatePresetId } from "@/components/filters/datePresets"
import { todayISO, startOfWeekISO, monthStartISO, monthsAgoISO } from "@/components/dashboard/atoms"

describe("datePresets", () => {
  it("exposes four presets", () => {
    expect(DATE_PRESETS.map((p) => p.id)).toEqual(["today", "week", "month", "3m"])
  })

  it("matchDatePresetId returns id for matching ranges", () => {
    expect(matchDatePresetId(todayISO(), todayISO())).toBe("today")
    expect(matchDatePresetId(startOfWeekISO(), todayISO(), "week")).toBe("week")
    expect(matchDatePresetId(monthStartISO(), todayISO(), "month")).toBe("month")
    expect(matchDatePresetId(monthsAgoISO(3), todayISO(), "3m")).toBe("3m")
  })

  it("matchDatePresetId returns empty for custom range", () => {
    expect(matchDatePresetId("2020-01-01", "2020-01-02")).toBe("")
    expect(matchDatePresetId("", todayISO())).toBe("")
  })

  it("prefers preferredId when multiple presets share a range", () => {
    const from = startOfWeekISO()
    const to = todayISO()
    if (from === todayISO()) {
      expect(matchDatePresetId(from, to, "week")).toBe("week")
      expect(matchDatePresetId(from, to, "today")).toBe("today")
    }
  })
})
