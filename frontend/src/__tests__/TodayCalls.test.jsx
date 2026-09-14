import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import api from "@/lib/api"
import TodayCalls from "@/pages/TodayCalls"
import { __setMockSearchParams, __getMockSetParams } from "react-router-dom"

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
  },
  formatApiError: jest.fn((detail) => String(detail)),
}))

jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}))

const queueItems = [
  {
    id: "lead-overdue",
    name: "Overdue Lead",
    phone: "+919111111111",
    source: "Website",
    pipeline_stage: "Contacted",
    disposition_name: "Call Back",
    carry_forward: true,
    follow_up_at: "2026-09-01T10:00:00.000Z",
    queue_reason: "overdue",
    days_overdue: 3,
    last_notes: "Missed two callbacks",
  },
  {
    id: "lead-today",
    name: "Today Lead",
    phone: "+919222222222",
    source: "Referral",
    pipeline_stage: "New",
    disposition_name: null,
    follow_up_at: "2026-09-04T15:00:00.000Z",
    queue_reason: "due_today",
    hours_until: 3,
    last_notes: null,
  },
  {
    id: "lead-assigned",
    name: "Assigned Lead",
    phone: "+919333333333",
    source: "Manual",
    pipeline_stage: "New",
    disposition_name: null,
    follow_up_at: null,
    queue_reason: "assigned_today",
  },
  {
    id: "lead-upcoming",
    name: "Upcoming Lead",
    phone: "+919444444444",
    source: "Website",
    pipeline_stage: "Qualified",
    disposition_name: "Interested",
    carry_forward: true,
    follow_up_at: "2026-09-08T10:00:00.000Z",
    queue_reason: "upcoming",
  },
]

const calledItems = [
  {
    id: "lead-called-a",
    name: "Called A",
    phone: "+919555555555",
    source: "Website",
    pipeline_stage: "Contacted",
    disposition_name: "Interested",
    carry_forward: true,
    queue_reason: "called_today",
  },
  {
    id: "lead-called-b",
    name: "Called B",
    phone: "+919666666666",
    source: "Manual",
    pipeline_stage: "New",
    disposition_name: "Call Back",
    carry_forward: true,
    queue_reason: "called_today",
  },
]

const mockCounts = {
  date: "2026-09-04",
  acw_pending_lead_id: null,
  counts: {
    overdue: 1,
    due_today: 1,
    assigned_today: 1,
    upcoming: 1,
    called_today: 2,
  },
  tab_counts: { queue: 4, acw_pending: 0 },
}

function itemsForUrl(url) {
  const qs = new URLSearchParams(url.split("?")[1] || "")
  const bucket = qs.get("bucket") || "all"
  if (bucket === "called_today") return calledItems
  if (bucket === "overdue") return queueItems.filter((l) => l.queue_reason === "overdue")
  if (bucket === "all") return queueItems
  return queueItems.filter((l) => l.queue_reason === bucket)
}

function mockApi(acwId = null) {
  api.get.mockImplementation((url) => {
    if (url.startsWith("/today-calls/counts")) {
      const payload = JSON.parse(JSON.stringify(mockCounts))
      if (acwId) {
        payload.acw_pending_lead_id = acwId
        payload.tab_counts = { queue: 4, acw_pending: 1 }
      }
      return Promise.resolve({ data: payload })
    }
    if (url.startsWith("/today-calls")) {
      const items = itemsForUrl(url)
      return Promise.resolve({
        data: {
          date: "2026-09-04",
          acw_pending_lead_id: acwId,
          items,
          total: items.length,
          page: 1,
          page_size: 50,
          bucket: new URLSearchParams(url.split("?")[1] || "").get("bucket") || "all",
          sort: "urgency",
        },
      })
    }
    if (url === "/dispositions") {
      return Promise.resolve({
        data: {
          dispositions: [
            { id: "d1", name: "Interested", active: true, color: "#0EA5E9", requires_acw: false },
          ],
        },
      })
    }
    if (url === "/leads/filter-options") {
      return Promise.resolve({
        data: {
          stages: ["New", "Contacted"],
          sources: ["Website", "Referral", "Manual"],
          dispositions: [{ id: "d1", name: "Interested" }, { id: "d2", name: "Call Back" }],
        },
      })
    }
    return Promise.resolve({ data: {} })
  })
  api.post.mockResolvedValue({ data: { acw: false, call: { id: "c1" } } })
}

describe("TodayCalls workbench", () => {
  beforeEach(() => {
    jest.clearAllMocks()
    __setMockSearchParams(new URLSearchParams())
    mockApi()
  })

  it("shows KPI counts and section order overdue first", async () => {
    render(<TodayCalls />)

    await waitFor(() => {
      expect(screen.getByTestId("kpi-overdue")).toHaveTextContent("1")
      expect(screen.getByTestId("kpi-due_today")).toHaveTextContent("1")
      expect(screen.getByTestId("kpi-all")).toHaveTextContent("4")
      expect(screen.getByTestId("section-overdue")).toBeInTheDocument()
    })

    expect(screen.getByTestId("overdue-banner")).toBeInTheDocument()
    expect(screen.getByTestId("filter-stage")).toBeInTheDocument()
    expect(screen.getByTestId("filter-source")).toBeInTheDocument()
    expect(screen.getByTestId("filter-disposition")).toBeInTheDocument()
    expect(screen.getByTestId("filter-sort")).toBeInTheDocument()
    expect(screen.getByTestId("kpi-acw")).toHaveTextContent("0")
    expect(screen.queryByTestId("dial-call-btn-lead-overdue")).not.toBeInTheDocument()
    expect(screen.getByTestId("log-call-btn-lead-overdue")).toBeInTheDocument()
    const sections = screen.getAllByTestId(/section-(overdue|due_today|assigned_today|upcoming)/)
    expect(sections[0]).toHaveAttribute("data-testid", "section-overdue")
    expect(api.get).toHaveBeenCalledWith("/today-calls/counts")
    expect(api.get).toHaveBeenCalledWith(expect.stringMatching(/^\/today-calls\?/))
  })

  it("requests default page_size 50", async () => {
    render(<TodayCalls />)
    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith("/today-calls?page=1&page_size=50")
    })
  })

  it("filters to overdue bucket only via count strip", async () => {
    const user = userEvent.setup()
    render(<TodayCalls />)

    await waitFor(() => {
      expect(screen.getByTestId("today-card-lead-overdue")).toBeInTheDocument()
    })

    await user.click(screen.getByTestId("kpi-overdue"))

    await waitFor(() => {
      const setParams = __getMockSetParams()
      expect(setParams).toHaveBeenCalled()
      const last = setParams.mock.calls.at(-1)[0]
      expect(last.get("bucket")).toBe("overdue")
    })
  })

  it("filters to called today via count strip", async () => {
    const user = userEvent.setup()
    __setMockSearchParams(new URLSearchParams("bucket=called_today"))
    render(<TodayCalls />)

    await waitFor(() => {
      expect(screen.getByTestId("section-called_today")).toBeInTheDocument()
      expect(screen.getByTestId("today-card-lead-called-a")).toBeInTheDocument()
      expect(screen.getByTestId("today-card-lead-called-b")).toBeInTheDocument()
    })
    expect(screen.queryByTestId("today-card-lead-overdue")).not.toBeInTheDocument()
    expect(screen.queryByTestId("section-overdue")).not.toBeInTheDocument()
  })

  it("shows last remarks on cards and in Log Call dialog", async () => {
    const user = userEvent.setup()
    render(<TodayCalls />)

    await waitFor(() => {
      expect(screen.getByTestId("today-last-remarks-lead-overdue")).toBeInTheDocument()
    })
    expect(screen.getByTestId("today-last-remarks-lead-overdue")).toHaveTextContent(
      "Missed two callbacks",
    )
    expect(screen.getByTestId("today-last-remarks-lead-today")).toHaveTextContent("—")

    await user.click(screen.getByTestId("log-call-btn-lead-overdue"))
    const dialog = await screen.findByTestId("log-call-dialog")
    expect(within(dialog).getByTestId("log-call-last-remarks")).toHaveTextContent(
      "Missed two callbacks",
    )
  })

  it("shows Remarks and posts /calls/log", async () => {
    const user = userEvent.setup()
    render(<TodayCalls />)

    await waitFor(() => {
      expect(screen.getByTestId("log-call-btn-lead-overdue")).toBeInTheDocument()
    })

    await user.click(screen.getByTestId("log-call-btn-lead-overdue"))
    const dialog = await screen.findByTestId("log-call-dialog")
    expect(within(dialog).getByLabelText("Remarks")).toBeInTheDocument()
    expect(screen.queryByLabelText("Notes")).not.toBeInTheDocument()

    await user.selectOptions(within(dialog).getByTestId("disposition-select"), "d1")
    await user.type(within(dialog).getByTestId("remarks-input"), "Workbench call")
    await user.click(within(dialog).getByTestId("submit-call-btn"))

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/calls/log",
        expect.objectContaining({
          lead_id: "lead-overdue",
          disposition_id: "d1",
          notes: "Workbench call",
        }),
      )
    })
  })

  it("keeps Log Call enabled when ACW pending and shows ACW count on KPI", async () => {
    mockApi("lead-overdue")
    render(<TodayCalls />)

    await waitFor(() => {
      expect(screen.getByTestId("log-call-btn-lead-overdue")).toBeEnabled()
    })
    expect(screen.getByTestId("acw-banner")).toHaveTextContent(/complete anytime/i)
    expect(screen.getByTestId("kpi-acw")).toHaveTextContent("1")
  })

  it("shows pagination when total exceeds page", async () => {
    api.get.mockImplementation((url) => {
      if (url.startsWith("/today-calls/counts")) {
        return Promise.resolve({ data: mockCounts })
      }
      if (url.startsWith("/today-calls")) {
        return Promise.resolve({
          data: {
            date: "2026-09-04",
            acw_pending_lead_id: null,
            items: queueItems,
            total: 87,
            page: 1,
            page_size: 50,
            bucket: "all",
            sort: "urgency",
          },
        })
      }
      if (url === "/dispositions") {
        return Promise.resolve({ data: { dispositions: [] } })
      }
      if (url === "/leads/filter-options") {
        return Promise.resolve({ data: { sources: [], dispositions: [] } })
      }
      return Promise.resolve({ data: {} })
    })

    render(<TodayCalls />)

    await waitFor(() => {
      expect(screen.getByTestId("table-pagination")).toBeInTheDocument()
    })
    expect(screen.getByTestId("pagination-range")).toHaveTextContent("1–50 of 87")
  })
})
