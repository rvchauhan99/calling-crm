import { inactiveMasterLabel, dispositionFilterOptions, agentFilterOptions } from "@/lib/masterOptions"

describe("masterOptions", () => {
  it("suffixes inactive names and keeps filter values as the real name", () => {
    expect(inactiveMasterLabel("Interested", true)).toBe("Interested")
    expect(inactiveMasterLabel("Old Disp", false)).toBe("Old Disp (inactive)")
    expect(dispositionFilterOptions([
      { name: "Interested", active: true },
      { name: "Old Disp", active: false },
    ])).toEqual([
      { value: "Interested", label: "Interested" },
      { value: "Old Disp", label: "Old Disp (inactive)" },
    ])
    expect(agentFilterOptions([
      { id: "a1", name: "Rohan", active: true },
      { id: "a2", name: "Retired", active: false },
    ])).toEqual([
      { value: "a1", label: "Rohan" },
      { value: "a2", label: "Retired (inactive)" },
    ])
  })
})
