import { render, screen, waitFor } from "@testing-library/react"
import { SourceSelect } from "@/components/leads/SourceSelect"
import api from "@/lib/api"

jest.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: jest.fn() },
}))

jest.mock("@/components/ui/searchable-select", () => ({
  SearchableSelect: ({ testId, options = [] }) => (
    <select data-testid={testId}>
      {options.map((o) => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  ),
}))

const sources = [
  { id: "s1", name: "Manual", active: true, creatable: true },
  { id: "s2", name: "Import", active: true, creatable: false },
  { id: "s3", name: "Old Portal", active: false, creatable: true },
]

describe("SourceSelect inactive masters", () => {
  beforeEach(() => {
    jest.clearAllMocks()
    api.get.mockResolvedValue({ data: { lead_sources: sources } })
  })

  it("hides inactive sources by default", async () => {
    render(<SourceSelect value="Manual" onChange={() => {}} />)
    await waitFor(() => {
      expect(screen.getByTestId("lead-field-source")).toHaveTextContent("Manual")
    })
    const select = screen.getByTestId("lead-field-source")
    expect(select).not.toHaveTextContent("Old Portal")
    expect(select).not.toHaveTextContent("Import")
  })

  it("shows inactive sources labeled when includeInactive is set", async () => {
    render(
      <SourceSelect
        value="all"
        onChange={() => {}}
        includeAll
        includeImport
        includeInactive
        testId="source-filter"
      />,
    )
    await waitFor(() => {
      expect(screen.getByTestId("source-filter")).toHaveTextContent("Old Portal (inactive)")
    })
    const select = screen.getByTestId("source-filter")
    expect(select).toHaveTextContent("Manual")
    expect(select).toHaveTextContent("Import")
    expect(select).toHaveTextContent("All sources")
  })
})
