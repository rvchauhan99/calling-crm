import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { useAuth } from "@/context/AuthContext"
import api from "@/lib/api"
import CallHistory from "@/pages/CallHistory"
import { __setMockSearchParams } from "react-router-dom"

jest.mock("@/context/AuthContext", () => ({
  useAuth: jest.fn(),
}))

jest.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: jest.fn(), post: jest.fn() },
  API: "http://localhost:8000/api",
  getToken: jest.fn(() => "t"),
  formatApiError: jest.fn((d) => String(d)),
}))

jest.mock("@/components/ui/searchable-select", () => ({
  SearchableSelect: ({ testId }) => <div data-testid={testId} />,
}))

jest.mock("sonner", () => ({ toast: { success: jest.fn(), error: jest.fn() } }))

describe("CallHistory filters", () => {
  beforeEach(() => {
    jest.clearAllMocks()
    __setMockSearchParams(new URLSearchParams())
    useAuth.mockReturnValue({
      can: () => true,
      dataScope: "ALL",
      user: { id: "a1", user_type: "admin" },
    })
    api.get.mockImplementation((url) => {
      if (url.startsWith("/call-history?")) {
        return Promise.resolve({
          data: { calls: [], total: 0, page: 1, page_size: 30 },
        })
      }
      if (url === "/dispositions") {
        return Promise.resolve({ data: { dispositions: [{ id: "d1", name: "Interested", active: true }] } })
      }
      if (url === "/dashboard/filter-options") {
        return Promise.resolve({ data: { agents: [{ id: "ag1", name: "Rohan" }] } })
      }
      return Promise.resolve({ data: {} })
    })
  })

  it("renders disposition and date filters", async () => {
    render(<CallHistory />)
    await waitFor(() => {
      expect(screen.getByTestId("call-history-filters")).toBeInTheDocument()
    })
    expect(screen.getByTestId("call-filter-disposition")).toBeInTheDocument()
    expect(screen.getByTestId("call-filter-from")).toBeInTheDocument()
    expect(screen.getByText("Disposition")).toBeInTheDocument()
  })

  it("opens lead 360 when phone is clicked", async () => {
    const user = userEvent.setup()
    api.get.mockImplementation((url) => {
      if (url.startsWith("/call-history?")) {
        return Promise.resolve({
          data: {
            calls: [{
              id: "c1",
              lead_id: "l1",
              lead_name: "Lead One",
              lead_phone: "+919999999999",
              agent_name: "Rohan",
              disposition_name: "Interested",
              duration: 30,
              notes: "",
              created_at: "2026-09-01T10:00:00.000Z",
            }],
            total: 1,
            page: 1,
            page_size: 30,
          },
        })
      }
      if (url === "/dispositions") {
        return Promise.resolve({ data: { dispositions: [] } })
      }
      if (url === "/dashboard/filter-options") {
        return Promise.resolve({ data: { agents: [] } })
      }
      if (url === "/leads/l1") {
        return Promise.resolve({
          data: {
            lead: {
              id: "l1", name: "Lead One", phone: "+919999999999",
              status: "active", pipeline_stage: "New",
            },
            calls: [],
            client: null,
            activity: [],
          },
        })
      }
      return Promise.resolve({ data: {} })
    })
    render(<CallHistory />)
    await waitFor(() => expect(screen.getByTestId("call-lead-phone-c1")).toBeInTheDocument())
    await user.click(screen.getByTestId("call-lead-phone-c1"))
    await waitFor(() => expect(screen.getByTestId("lead-360")).toBeInTheDocument())
  })
})
