import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { useAuth } from "@/context/AuthContext"
import api from "@/lib/api"
import { toast } from "sonner"
import Clients from "@/pages/Clients"
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

jest.mock("@/components/leads/Lead360Sheet", () => ({
  Lead360Sheet: () => null,
}))

jest.mock("sonner", () => ({ toast: { success: jest.fn(), error: jest.fn() } }))

const sampleClient = {
  id: "c-undo-1",
  name: "TEST_UndoBtn",
  phone: "+917700000001",
  email: "",
  assigned_name: "Rohan",
  ftd_at: "2026-09-12T10:00:00.000Z",
  balance: 103,
  status: "active",
  lead_id: "l-undo-1",
  notes: [],
}

function mockListApis() {
  api.get.mockImplementation((url) => {
    if (url.startsWith("/clients?") && !url.includes("/clients/c-")) {
      return Promise.resolve({
        data: {
          clients: [sampleClient],
          total: 1,
          page: 1,
          page_size: 25,
        },
      })
    }
    if (url === "/clients/tab-counts") {
      return Promise.resolve({ data: { active: 1, inactive: 0 } })
    }
    if (url === "/clients/c-undo-1") {
      return Promise.resolve({
        data: {
          client: sampleClient,
          ledger: [{
            id: "e1",
            type: "credit",
            category: "deposit",
            amount: 103,
            balance_after: 103,
            created_at: "2026-09-12T10:00:00.000Z",
          }],
        },
      })
    }
    return Promise.resolve({ data: {} })
  })
}

describe("Clients undo conversion", () => {
  beforeEach(() => {
    jest.clearAllMocks()
    __setMockSearchParams(new URLSearchParams())
    mockListApis()
  })

  it("shows Undo conversion when user has clients:edit", async () => {
    const user = userEvent.setup()
    useAuth.mockReturnValue({
      can: (p) => p === "clients:edit" || p === "leads:view" || p === "clients:view",
      dataScope: "ALL",
      user: { id: "admin-1", user_type: "admin" },
    })
    render(<Clients />)
    await waitFor(() => expect(screen.getByTestId("client-row-c-undo-1")).toBeInTheDocument())
    await user.click(screen.getByTestId("client-row-c-undo-1"))
    await waitFor(() => expect(screen.getByTestId("client-detail")).toBeInTheDocument())
    expect(screen.getByTestId("client-unconvert-btn")).toBeInTheDocument()
  })

  it("hides Undo conversion without clients:edit", async () => {
    const user = userEvent.setup()
    useAuth.mockReturnValue({
      can: (p) => p === "clients:view" || p === "leads:view",
      dataScope: "OWN",
      user: { id: "agent-1", user_type: "employee" },
    })
    render(<Clients />)
    await waitFor(() => expect(screen.getByTestId("client-row-c-undo-1")).toBeInTheDocument())
    await user.click(screen.getByTestId("client-row-c-undo-1"))
    await waitFor(() => expect(screen.getByTestId("client-detail")).toBeInTheDocument())
    expect(screen.queryByTestId("client-unconvert-btn")).not.toBeInTheDocument()
  })

  it("confirms and posts unconvert then closes sheet", async () => {
    const user = userEvent.setup()
    useAuth.mockReturnValue({
      can: () => true,
      dataScope: "ALL",
      user: { id: "admin-1", user_type: "admin" },
    })
    window.confirm = jest.fn(() => true)
    api.post.mockResolvedValue({ data: { unconverted: true, client_id: "c-undo-1" } })

    render(<Clients />)
    await waitFor(() => expect(screen.getByTestId("client-row-c-undo-1")).toBeInTheDocument())
    await user.click(screen.getByTestId("client-row-c-undo-1"))
    await waitFor(() => expect(screen.getByTestId("client-unconvert-btn")).toBeInTheDocument())
    await user.click(screen.getByTestId("client-unconvert-btn"))

    expect(window.confirm).toHaveBeenCalled()
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/clients/c-undo-1/unconvert")
    })
    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith("Conversion undone · Removed from Clients")
    })
    await waitFor(() => {
      expect(screen.queryByTestId("client-detail")).not.toBeInTheDocument()
    })
  })

  it("does not call API when confirm is cancelled", async () => {
    const user = userEvent.setup()
    useAuth.mockReturnValue({
      can: () => true,
      dataScope: "ALL",
      user: { id: "admin-1", user_type: "admin" },
    })
    window.confirm = jest.fn(() => false)

    render(<Clients />)
    await waitFor(() => expect(screen.getByTestId("client-row-c-undo-1")).toBeInTheDocument())
    await user.click(screen.getByTestId("client-row-c-undo-1"))
    await waitFor(() => expect(screen.getByTestId("client-unconvert-btn")).toBeInTheDocument())
    await user.click(screen.getByTestId("client-unconvert-btn"))

    expect(api.post).not.toHaveBeenCalled()
  })
})
