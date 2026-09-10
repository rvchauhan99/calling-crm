import { render, screen, waitFor, fireEvent } from "@testing-library/react"
import { useAuth } from "@/context/AuthContext"
import api from "@/lib/api"
import LeadSources from "@/pages/LeadSources"

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

const mockRows = [
  {
    id: "sys-manual",
    name: "Manual",
    order: 7,
    active: true,
    creatable: true,
    is_system: true,
  },
  {
    id: "sys-import",
    name: "Import",
    order: 8,
    active: true,
    creatable: false,
    is_system: true,
  },
  {
    id: "custom-1",
    name: "Partner Portal",
    order: 9,
    active: true,
    creatable: true,
    is_system: false,
  },
]

describe("LeadSources page", () => {
  beforeEach(() => {
    jest.clearAllMocks()
    useAuth.mockReturnValue({
      can: () => true,
      dataScope: "ALL",
      user: { id: "admin-1", user_type: "admin" },
    })
    api.get.mockResolvedValue({ data: { lead_sources: mockRows } })
    api.post.mockResolvedValue({ data: { lead_source: { id: "new-1", name: "Trade Show" } } })
  })

  it("lists sources and saves a new one", async () => {
    render(<LeadSources />)

    await waitFor(() => {
      expect(screen.getByTestId("lead-sources-page")).toBeInTheDocument()
      expect(screen.getByTestId("lead-source-row-custom-1")).toBeInTheDocument()
    })

    fireEvent.click(screen.getByTestId("new-lead-source-btn"))
    await waitFor(() => {
      expect(screen.getByTestId("lead-source-dialog")).toBeInTheDocument()
    })

    fireEvent.change(screen.getByTestId("lead-source-name"), {
      target: { value: "Trade Show" },
    })
    fireEvent.click(screen.getByTestId("save-lead-source-btn"))

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/lead-sources", expect.objectContaining({
        name: "Trade Show",
        creatable: true,
        active: true,
      }))
    })
  })

  it("hides create when RBAC denies lead_sources:create", async () => {
    useAuth.mockReturnValue({
      can: (perm) => perm !== "lead_sources:create",
      dataScope: "ALL",
      user: { id: "agent-1" },
    })
    render(<LeadSources />)
    await waitFor(() => {
      expect(screen.getByTestId("lead-sources-page")).toBeInTheDocument()
    })
    expect(screen.queryByTestId("new-lead-source-btn")).not.toBeInTheDocument()
  })

  it("does not show delete for system sources", async () => {
    render(<LeadSources />)
    await waitFor(() => {
      expect(screen.getByTestId("lead-source-row-sys-manual")).toBeInTheDocument()
    })
    expect(screen.queryByTestId("del-lead-source-sys-manual")).not.toBeInTheDocument()
    expect(screen.queryByTestId("del-lead-source-sys-import")).not.toBeInTheDocument()
    expect(screen.getByTestId("del-lead-source-custom-1")).toBeInTheDocument()
  })
})
