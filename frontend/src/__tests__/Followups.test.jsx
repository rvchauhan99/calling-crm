import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import api from "@/lib/api"
import Followups, { classifyFollowup, sortFollowups } from "@/pages/Followups"
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
    put: jest.fn(),
  },
  formatApiError: jest.fn((detail) => String(detail)),
}))

jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}))

const FIXED_NOW = new Date("2026-09-04T12:00:00")

const dayOffsetIso = (dayOffset, hour = 15) => {
  const d = new Date()
  d.setHours(hour, 0, 0, 0)
  d.setDate(d.getDate() + dayOffset)
  return d.toISOString()
}

const mockFollowups = [
  {
    id: "fu-overdue",
    name: "Overdue Lead",
    phone: "+919222222222",
    disposition_name: "Interested",
    follow_up_at: dayOffsetIso(-3, 10),
    pipeline_stage: "Contacted",
    last_notes: "Asked for pricing",
  },
  {
    id: "fu-today",
    name: "Today Lead",
    phone: "+919333333333",
    disposition_name: "Call Back",
    follow_up_at: dayOffsetIso(0, 15),
    pipeline_stage: "Qualified",
    last_notes: null,
  },
  {
    id: "fu-upcoming",
    name: "Upcoming Lead",
    phone: "+919111111111",
    disposition_name: "Call Back",
    follow_up_at: dayOffsetIso(6, 10),
    pipeline_stage: "New",
    last_notes: "Will call next week",
  },
]

function rowsForUrl(url) {
  const qs = new URLSearchParams(url.split("?")[1] || "")
  const bucket = qs.get("bucket") || "all"
  const items = bucket === "all"
    ? mockFollowups
    : mockFollowups.filter((l) => classifyFollowup(l.follow_up_at) === bucket)
  return items
}

function mockApi(acwId = null) {
  api.get.mockImplementation((url) => {
    if (url.startsWith("/followups")) {
      const items = rowsForUrl(url)
      return Promise.resolve({
        data: { followups: items, total: items.length, page: 1, page_size: 25 },
      })
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
    __setMockSearchParams(new URLSearchParams())
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

  it("requests page and page_size and shows counted pagination", async () => {
    api.get.mockImplementation((url) => {
      if (url.startsWith("/followups")) {
        return Promise.resolve({
          data: {
            followups: mockFollowups,
            total: 87,
            page: 1,
            page_size: 25,
          },
        })
      }
      if (url === "/dispositions") {
        return Promise.resolve({ data: { dispositions: [] } })
      }
      if (url === "/today-calls") {
        return Promise.resolve({ data: { leads: [], acw_pending_lead_id: null } })
      }
      return Promise.resolve({ data: {} })
    })

    render(<Followups />)

    await waitFor(() => {
      expect(screen.getByTestId("table-pagination")).toBeInTheDocument()
    })
    expect(api.get).toHaveBeenCalledWith("/followups?page=1&page_size=25")
    expect(screen.getByTestId("pagination-range")).toHaveTextContent("1–25 of 87")
    expect(screen.getByText("87 scheduled callbacks")).toBeInTheDocument()
    expect(screen.getByTestId("next-page")).toBeEnabled()
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

  it("writes overdue bucket and resets page on filter click", async () => {
    const user = userEvent.setup()
    render(<Followups />)

    await waitFor(() => {
      expect(screen.getByTestId("followup-row-fu-overdue")).toBeInTheDocument()
    })

    await user.click(screen.getByTestId("followups-filter-overdue"))

    const setParams = __getMockSetParams()
    expect(setParams).toHaveBeenCalled()
    const last = setParams.mock.calls[setParams.mock.calls.length - 1][0]
    const qs = last instanceof URLSearchParams ? last : new URLSearchParams(last)
    expect(qs.get("bucket")).toBe("overdue")
    expect(qs.get("page")).toBe("1")
  })

  it("honors bucket from URL and shows only that page", async () => {
    __setMockSearchParams(new URLSearchParams("bucket=overdue"))
    render(<Followups />)

    await waitFor(() => {
      expect(screen.getByTestId("followup-row-fu-overdue")).toBeInTheDocument()
    })
    expect(api.get).toHaveBeenCalledWith("/followups?page=1&page_size=25&bucket=overdue")
    expect(screen.getByTestId("followup-row-fu-overdue")).toBeInTheDocument()
    expect(screen.queryByTestId("followup-row-fu-today")).not.toBeInTheDocument()
    expect(screen.queryByTestId("followup-row-fu-upcoming")).not.toBeInTheDocument()
  })

  it("shows last remarks in table and Log Call dialog", async () => {
    const user = userEvent.setup()
    render(<Followups />)

    await waitFor(() => {
      expect(screen.getByTestId("followup-last-remarks-fu-overdue")).toBeInTheDocument()
    })
    expect(screen.getByTestId("followup-last-remarks-fu-overdue")).toHaveTextContent(
      "Asked for pricing",
    )
    expect(screen.getByTestId("followup-last-remarks-fu-today")).toHaveTextContent("—")

    await user.click(screen.getByTestId("log-call-btn-fu-overdue"))
    const dialog = await screen.findByTestId("log-call-dialog")
    expect(within(dialog).getByTestId("log-call-last-remarks")).toHaveTextContent(
      "Asked for pricing",
    )
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
          follow_up_at: null,
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
