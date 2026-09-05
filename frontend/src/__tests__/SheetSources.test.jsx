import { render, screen, waitFor, fireEvent } from "@testing-library/react"
import { useAuth } from "@/context/AuthContext"
import api from "@/lib/api"
import SheetSources from "@/pages/SheetSources"

jest.mock("@/components/ui/searchable-select", () => ({
  SearchableSelect: ({ label, value, onChange, options, testId }) => (
    <div data-testid={testId}>
      {label && <span>{label}</span>}
      <select
        aria-label={label || testId}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        data-testid={`${testId}-select`}
      >
        {(options || []).map((o) => (
          <option key={o.value || "empty"} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
  ),
}))

jest.mock("@/context/AuthContext", () => ({
  useAuth: jest.fn(),
}))

jest.mock("@/lib/api", () => ({
  __esModule: true,
  default: {
    get: jest.fn(),
    post: jest.fn(),
    put: jest.fn(),
    delete: jest.fn(),
  },
  API: "http://localhost:8000/api",
  getToken: jest.fn(() => "test-token"),
  formatApiError: jest.fn((detail) => String(detail)),
}))

jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn(), message: jest.fn() },
}))

const mockSource = {
  id: "src-1",
  name: "Bax Meta Lead Ads (sample)",
  sheet_url: "https://docs.google.com/spreadsheets/d/abc/edit",
  enabled: true,
  auto_assign: false,
  source: "Facebook Ads",
  preset: "meta_lead_ads",
  column_map: {
    name: "full_name",
    phone: "phone_number",
    email: "email",
    city: "",
    external_id: "id",
  },
  last_status: "ok",
  last_result: { created: 0, duplicates: 18, invalid: 1 },
}

describe("SheetSources column mapping", () => {
  beforeEach(() => {
    jest.clearAllMocks()
    useAuth.mockReturnValue({
      can: () => true,
      dataScope: "ALL",
      user: { id: "admin-1", user_type: "admin" },
    })
    api.get.mockResolvedValue({ data: { sheet_sources: [mockSource] } })
  })

  it("renders list and opens dialog with Meta default map", async () => {
    render(<SheetSources />)

    await waitFor(() => {
      expect(screen.getByTestId("sheet-sources-page")).toBeInTheDocument()
      expect(screen.getByTestId("sheet-source-row-src-1")).toBeInTheDocument()
    })

    fireEvent.click(screen.getByTestId("new-sheet-source-btn"))

    await waitFor(() => {
      expect(screen.getByTestId("sheet-source-dialog")).toBeInTheDocument()
    })

    expect(screen.getByTestId("sheet-column-mapping")).toBeInTheDocument()
    expect(screen.getByTestId("sheet-map-name-select")).toHaveValue("full_name")
    expect(screen.getByTestId("sheet-map-phone-select")).toHaveValue("phone_number")
    expect(screen.getByTestId("sheet-source-auto-assign")).toBeInTheDocument()
  })

  it("load columns updates options from inspect", async () => {
    api.post.mockImplementation((url) => {
      if (url === "/sheet-sources/inspect") {
        return Promise.resolve({
          data: {
            headers: ["customer name", "whatsapp", "mail"],
            suggested_map: {
              name: "customer name",
              phone: "whatsapp",
              email: "mail",
              city: "",
              external_id: "",
            },
          },
        })
      }
      return Promise.resolve({ data: {} })
    })

    render(<SheetSources />)
    await waitFor(() => screen.getByTestId("new-sheet-source-btn"))
    fireEvent.click(screen.getByTestId("new-sheet-source-btn"))

    fireEvent.change(screen.getByTestId("sheet-source-url"), {
      target: { value: "https://docs.google.com/spreadsheets/d/xyz/edit" },
    })
    fireEvent.click(screen.getByTestId("sheet-load-columns"))

    await waitFor(() => {
      expect(screen.getByTestId("sheet-headers-count")).toHaveTextContent("3 columns")
    })
    expect(screen.getByTestId("sheet-map-name-select")).toHaveValue("customer name")
    expect(screen.getByTestId("sheet-map-phone-select")).toHaveValue("whatsapp")
  })

  it("changing preset resets column map to defaults", async () => {
    render(<SheetSources />)
    await waitFor(() => screen.getByTestId("new-sheet-source-btn"))
    fireEvent.click(screen.getByTestId("new-sheet-source-btn"))

    fireEvent.change(screen.getByTestId("sheet-source-preset-select"), {
      target: { value: "generic" },
    })

    await waitFor(() => {
      expect(screen.getByTestId("sheet-map-name-select")).toHaveValue("name")
      expect(screen.getByTestId("sheet-map-phone-select")).toHaveValue("phone")
    })
  })

  it("save posts column_map", async () => {
    api.post.mockResolvedValue({ data: { sheet_source: { id: "new" } } })

    render(<SheetSources />)
    await waitFor(() => screen.getByTestId("new-sheet-source-btn"))
    fireEvent.click(screen.getByTestId("new-sheet-source-btn"))

    fireEvent.change(screen.getByTestId("sheet-source-name"), {
      target: { value: "My Sheet" },
    })
    fireEvent.change(screen.getByTestId("sheet-source-url"), {
      target: { value: "https://docs.google.com/spreadsheets/d/xyz/edit" },
    })
    fireEvent.click(screen.getByTestId("save-sheet-source-btn"))

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/sheet-sources",
        expect.objectContaining({
          name: "My Sheet",
          column_map: expect.objectContaining({
            name: "full_name",
            phone: "phone_number",
          }),
        }),
      )
    })
  })

  it("hides create when can() denies", async () => {
    useAuth.mockReturnValue({
      can: () => false,
      dataScope: "OWN",
      user: { id: "agent-1", user_type: "caller" },
    })
    render(<SheetSources />)
    await waitFor(() => screen.getByTestId("sheet-sources-page"))
    expect(screen.queryByTestId("new-sheet-source-btn")).not.toBeInTheDocument()
  })
})
