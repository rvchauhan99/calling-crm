import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import api from "@/lib/api"
import Followups, { classifyFollowup, sortFollowups } from "@/pages/Followups"

jest.mock("@/context/AuthContext", () => ({
  useAuth: () => ({ can: () => true, dataScope: "ALL", user: { id: "u1" } }),
}))

jest.mock("@/components/ui/searchable-select", () => ({
  SearchableSelect: ({ label, testId, value, onChange, options = [] }) => (
    <div>
      {label && <label htmlFor={testId}>{label}</label>}
      <select
        id={testId}
        data-testid={testId}
        value={value || ""}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">Select</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
  ),
}))

jest.mock("@/lib/api", () => ({
  __esModule: true,
  default: {
    get: jest.fn(),
    post: jest.fn(),
    put: jest.fn(),
  },
  formatApiError: jest.fn((detail) => String(detail)),
}))

jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}))

const FIXED_NOW = new Date("2026-09-04T12:00:00")

const mockFollowups = [
  {
    id: "fu-upcoming",
    name: "Upcoming Lead",
    phone: "+919111111111",
    disposition_name: "Call Back",
    follow_up_at: "2026-09-10T10:00:00.000Z",
    pipeline_stage: "New",
  },
  {
    id: "fu-overdue",
    name: "Overdue Lead",
    phone: "+919222222222",
    disposition_name: "Interested",
    follow_up_at: "2026-09-01T10:00:00.000Z",
    pipeline_stage: "Contacted",
  },
  {
    id: "fu-today",
    name: "Today Lead",
    phone: "+919333333333",
    disposition_name: "Call Back",
    follow_up_at: new Date(2026, 8, 4, 15, 0, 0).toISOString(),
    pipeline_stage: "Qualified",
  },
]

function mockApi(acwId = null) {
  api.get.mockImplementation((url) => {
    if (url === "/followups") {
      return Promise.resolve({ data: { followups: mockFollowups } })
    }
    if (url === "/dispositions") {
      return Promise.resolve({
        data: {
          dispositions: [
            { id: "disp-1", name: "Interested", active: true, color: "#0EA5E9", requires_acw: false },
          ],
        },
      })
    }
    if (url === "/today-calls") {
      return Promise.resolve({ data: { leads: [], acw_pending_lead_id: acwId, date: "2026-09-04" } })
    }
    return Promise.resolve({ data: {} })
  })
  api.post.mockResolvedValue({ data: { acw: false, call: { id: "c1" } } })
}

describe("classifyFollowup / sortFollowups", () => {
  it("classifies overdue, today, and upcoming", () => {
    expect(classifyFollowup("2026-09-01T10:00:00.000Z", FIXED_NOW)).toBe("overdue")
    expect(classifyFollowup(new Date(2026, 8, 4, 9, 0, 0).toISOString(), FIXED_NOW)).toBe("today")
    expect(classifyFollowup("2026-09-10T10:00:00.000Z", FIXED_NOW)).toBe("upcoming")
  })

  it("sorts overdue then today then upcoming", () => {
    const sorted = sortFollowups(mockFollowups, FIXED_NOW)
    expect(sorted.map((x) => x.id)).toEqual(["fu-overdue", "fu-today", "fu-upcoming"])
  })
})

describe("Followups page", () => {
  beforeEach(() => {
    jest.clearAllMocks()
    mockApi()
  })

  it("renders Log Call action and does not show Done", async () => {
    render(<Followups />)

    await waitFor(() => {
      expect(screen.getByTestId("followups-page")).toBeInTheDocument()
      expect(screen.getByTestId("followup-row-fu-overdue")).toBeInTheDocument()
    })

    expect(screen.getByTestId("log-call-btn-fu-overdue")).toBeInTheDocument()
    expect(screen.getByTestId("log-call-btn-fu-today")).toBeInTheDocument()
    expect(screen.queryByTestId("clear-followup-fu-overdue")).not.toBeInTheDocument()
    expect(screen.queryByText("Done")).not.toBeInTheDocument()
  })

  it("orders rows overdue, today, then upcoming", async () => {
    render(<Followups />)

    await waitFor(() => {
      expect(screen.getByTestId("followup-row-fu-overdue")).toBeInTheDocument()
    })

    const rows = screen.getAllByTestId(/followup-row-/)
    expect(rows.map((r) => r.getAttribute("data-testid"))).toEqual([
      "followup-row-fu-overdue",
      "followup-row-fu-today",
      "followup-row-fu-upcoming",
    ])
    expect(rows[0]).toHaveAttribute("data-category", "overdue")
    expect(rows[1]).toHaveAttribute("data-category", "today")
    expect(rows[2]).toHaveAttribute("data-category", "upcoming")
  })

  it("filters to overdue only", async () => {
    const user = userEvent.setup()
    render(<Followups />)

    await waitFor(() => {
      expect(screen.getByTestId("followup-row-fu-overdue")).toBeInTheDocument()
    })

    await user.click(screen.getByTestId("followups-filter-overdue"))

    expect(screen.getByTestId("followup-row-fu-overdue")).toBeInTheDocument()
    expect(screen.queryByTestId("followup-row-fu-today")).not.toBeInTheDocument()
    expect(screen.queryByTestId("followup-row-fu-upcoming")).not.toBeInTheDocument()
  })

  it("opens Log Call dialog with Remarks and posts /calls/log", async () => {
    const user = userEvent.setup()
    render(<Followups />)

    await waitFor(() => {
      expect(screen.getByTestId("log-call-btn-fu-overdue")).toBeInTheDocument()
    })

    await user.click(screen.getByTestId("log-call-btn-fu-overdue"))

    const dialog = await screen.findByTestId("log-call-dialog")
    expect(within(dialog).getByLabelText("Remarks")).toBeInTheDocument()
    expect(within(dialog).getByTestId("remarks-input")).toBeInTheDocument()

    await user.selectOptions(within(dialog).getByTestId("disposition-select"), "disp-1")
    await user.type(within(dialog).getByTestId("remarks-input"), "Called back customer")
    await user.click(within(dialog).getByTestId("submit-call-btn"))

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/calls/log",
        expect.objectContaining({
          lead_id: "fu-overdue",
          disposition_id: "disp-1",
          notes: "Called back customer",
        }),
      )
    })
  })

  it("keeps Log Call enabled when ACW is pending on another lead", async () => {
    mockApi("other-lead")
    render(<Followups />)

    await waitFor(() => {
      expect(screen.getByTestId("log-call-btn-fu-overdue")).toBeEnabled()
    })
    expect(screen.getByTestId("acw-banner")).toHaveTextContent(/complete anytime/i)
  })
})
