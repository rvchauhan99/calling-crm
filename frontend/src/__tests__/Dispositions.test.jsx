import { render, screen, waitFor, fireEvent } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { useAuth } from "@/context/AuthContext"
import api from "@/lib/api"
import Dispositions, { formatDispositionActivityMeta } from "@/pages/Dispositions"

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

jest.mock("@/components/ui/searchable-select", () => ({
  SearchableSelect: () => null,
}))

jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn(), message: jest.fn() },
}))

const mockDisp = {
  id: "disp-1",
  name: "Ringing",
  slot: 1,
  order: 1,
  type: "carry_forward",
  requires_acw: false,
  color: "#0EA5E9",
  active: true,
  default_pipeline_stage: "Contacted",
  converts_to_client: false,
}

describe("formatDispositionActivityMeta", () => {
  it("formats field changes for updates", () => {
    const text = formatDispositionActivityMeta({
      name: "Ringing",
      changes: {
        type: { from: "carry_forward", to: "non_carry_forward" },
        active: { from: true, to: false },
      },
    })
    expect(text).toContain("type: carry_forward → non_carry_forward")
    expect(text).toContain("active: Yes → No")
  })
})

describe("Dispositions activity history", () => {
  beforeEach(() => {
    jest.clearAllMocks()
    useAuth.mockReturnValue({
      can: () => true,
      dataScope: "ALL",
      user: { id: "admin-1", user_type: "admin" },
    })
    api.get.mockImplementation((url) => {
      if (url === "/dispositions") {
        return Promise.resolve({ data: { dispositions: [mockDisp] } })
      }
      if (url.startsWith("/dispositions/activity")) {
        return Promise.resolve({
          data: {
            logs: [{
              id: "log-all-1",
              action: "update",
              actor_name: "Admin",
              created_at: "2026-09-14T10:00:00+00:00",
              meta: {
                name: "Ringing",
                changes: { type: { from: "carry_forward", to: "non_carry_forward" } },
              },
            }],
            total: 1,
          },
        })
      }
      if (url === "/dispositions/disp-1/activity") {
        return Promise.resolve({
          data: {
            logs: [{
              id: "log-row-1",
              action: "update",
              actor_name: "Admin",
              created_at: "2026-09-14T10:00:00+00:00",
              meta: {
                name: "Ringing",
                changes: { requires_acw: { from: false, to: true } },
              },
            }],
          },
        })
      }
      return Promise.resolve({ data: {} })
    })
  })

  it("opens page-level activity sheet with disposition changes", async () => {
    render(<Dispositions />)

    await waitFor(() => {
      expect(screen.getByTestId("disp-activity-btn")).toBeInTheDocument()
    })

    await userEvent.click(screen.getByTestId("disp-activity-btn"))

    await waitFor(() => {
      expect(screen.getByTestId("disp-activity-sheet")).toBeInTheDocument()
      expect(screen.getByTestId("disp-activity-row-log-all-1")).toBeInTheDocument()
    })
    expect(screen.getByText(/type: carry_forward → non_carry_forward/)).toBeInTheDocument()
    expect(api.get).toHaveBeenCalledWith("/dispositions/activity?page=1&page_size=100")
  })

  it("opens per-row history sheet with field diffs", async () => {
    render(<Dispositions />)

    await waitFor(() => {
      expect(screen.getByTestId("disp-history-disp-1")).toBeInTheDocument()
    })

    fireEvent.click(screen.getByTestId("disp-history-disp-1"))

    await waitFor(() => {
      expect(screen.getByTestId("disp-activity-sheet")).toBeInTheDocument()
      expect(screen.getByTestId("disp-activity-row-log-row-1")).toBeInTheDocument()
    })
    expect(screen.getByText(/requires_acw: No → Yes/)).toBeInTheDocument()
    expect(api.get).toHaveBeenCalledWith("/dispositions/disp-1/activity")
  })

  it("hides activity controls without dispositions:view", async () => {
    useAuth.mockReturnValue({
      can: (perm) => perm !== "dispositions:view",
      dataScope: "ALL",
      user: { id: "admin-1" },
    })
    render(<Dispositions />)
    await waitFor(() => {
      expect(screen.getByTestId("dispositions-page")).toBeInTheDocument()
      expect(screen.getByTestId("disp-row-disp-1")).toBeInTheDocument()
    })
    expect(screen.queryByTestId("disp-activity-btn")).not.toBeInTheDocument()
    expect(screen.queryByTestId("disp-history-disp-1")).not.toBeInTheDocument()
  })
})
