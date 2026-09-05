import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import api from "@/lib/api"
import TodayCalls from "@/pages/TodayCalls"

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

const mockWorkbench = {
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
  buckets: {
    overdue: [{
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
    }],
    due_today: [{
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
    }],
    assigned_today: [{
      id: "lead-assigned",
      name: "Assigned Lead",
      phone: "+919333333333",
      source: "Manual",
      pipeline_stage: "New",
      disposition_name: null,
      follow_up_at: null,
      queue_reason: "assigned_today",
    }],
    upcoming: [{
      id: "lead-upcoming",
      name: "Upcoming Lead",
      phone: "+919444444444",
      source: "Website",
      pipeline_stage: "Qualified",
      disposition_name: "Interested",
      carry_forward: true,
      follow_up_at: "2026-09-08T10:00:00.000Z",
      queue_reason: "upcoming",
    }],
    called_today: [{
      id: "lead-called-a",
      name: "Called A",
      phone: "+919555555555",
      source: "Website",
      pipeline_stage: "Contacted",
      disposition_name: "Interested",
      carry_forward: true,
      queue_reason: "called_today",
    }, {
      id: "lead-called-b",
      name: "Called B",
      phone: "+919666666666",
      source: "Manual",
      pipeline_stage: "New",
      disposition_name: "Call Back",
      carry_forward: true,
      queue_reason: "called_today",
    }],
  },
  leads: [],
}

describe("TodayCalls workbench", () => {
  beforeEach(() => {
    jest.clearAllMocks()
    mockWorkbench.leads = [
      ...mockWorkbench.buckets.overdue,
      ...mockWorkbench.buckets.due_today,
      ...mockWorkbench.buckets.assigned_today,
      ...mockWorkbench.buckets.upcoming,
    ]
    api.get.mockImplementation((url) => {
      if (url === "/today-calls") {
        return Promise.resolve({ data: JSON.parse(JSON.stringify(mockWorkbench)) })
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
      return Promise.resolve({ data: {} })
    })
    api.post.mockResolvedValue({ data: { acw: false, call: { id: "c1" } } })
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
    expect(screen.queryByTestId("filter-bucket-all")).not.toBeInTheDocument()
    expect(screen.queryByTestId("tab-queue")).not.toBeInTheDocument()
    expect(screen.queryByTestId("tab-acw-pending")).not.toBeInTheDocument()
    expect(screen.getByTestId("filter-stage")).toBeInTheDocument()
    expect(screen.getByTestId("filter-source")).toBeInTheDocument()
    expect(screen.getByTestId("filter-disposition")).toBeInTheDocument()
    expect(screen.getByTestId("filter-sort")).toBeInTheDocument()
    expect(screen.getByTestId("kpi-acw")).toHaveTextContent("0")
    const sections = screen.getAllByTestId(/section-(overdue|due_today|assigned_today|upcoming)/)
    expect(sections[0]).toHaveAttribute("data-testid", "section-overdue")
  })

  it("filters to overdue bucket only via count strip", async () => {
    const user = userEvent.setup()
    render(<TodayCalls />)

    await waitFor(() => {
      expect(screen.getByTestId("today-card-lead-overdue")).toBeInTheDocument()
    })

    await user.click(screen.getByTestId("kpi-overdue"))

    expect(screen.getByTestId("today-card-lead-overdue")).toBeInTheDocument()
    expect(screen.queryByTestId("today-card-lead-today")).not.toBeInTheDocument()
    expect(screen.queryByTestId("today-card-lead-assigned")).not.toBeInTheDocument()
  })

  it("filters to called today via count strip", async () => {
    const user = userEvent.setup()
    render(<TodayCalls />)

    await waitFor(() => {
      expect(screen.getByTestId("kpi-called_today")).toBeEnabled()
      expect(screen.getByTestId("kpi-called_today")).toHaveTextContent("2")
    })

    await user.click(screen.getByTestId("kpi-called_today"))

    expect(screen.getByTestId("section-called_today")).toBeInTheDocument()
    expect(screen.getByTestId("today-card-lead-called-a")).toBeInTheDocument()
    expect(screen.getByTestId("today-card-lead-called-b")).toBeInTheDocument()
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
    api.get.mockImplementation((url) => {
      if (url === "/today-calls") {
        const payload = JSON.parse(JSON.stringify(mockWorkbench))
        payload.acw_pending_lead_id = "lead-overdue"
        payload.tab_counts = { queue: 4, acw_pending: 1 }
        return Promise.resolve({ data: payload })
      }
      if (url === "/dispositions") {
        return Promise.resolve({ data: { dispositions: [] } })
      }
      return Promise.resolve({ data: {} })
    })

    render(<TodayCalls />)

    await waitFor(() => {
      expect(screen.getByTestId("log-call-btn-lead-overdue")).toBeEnabled()
    })
    expect(screen.getByTestId("acw-banner")).toHaveTextContent(/complete anytime/i)
    expect(screen.queryByTestId("tab-acw-pending")).not.toBeInTheDocument()
    expect(screen.queryByTestId("acw-pending-panel")).not.toBeInTheDocument()
    expect(screen.getByTestId("kpi-acw")).toHaveTextContent("1")
  })
})
