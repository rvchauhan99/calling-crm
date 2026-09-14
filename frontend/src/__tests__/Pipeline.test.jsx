import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { useAuth } from "@/context/AuthContext"
import api from "@/lib/api"
import Pipeline from "@/pages/Pipeline"
import { __setMockSearchParams } from "react-router-dom"

jest.mock("@/context/AuthContext", () => ({
  useAuth: jest.fn(),
}))

jest.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: jest.fn(), post: jest.fn(), put: jest.fn() },
  formatApiError: jest.fn((d) => String(d)),
}))

jest.mock("@/components/ui/searchable-select", () => ({
  SearchableSelect: ({ testId, label, value, onChange, options = [] }) => (
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

jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}))

const board = {
  stages: ["New", "Contacted", "Qualified", "Proposal", "Won", "Lost"],
  counts: { New: 1, Contacted: 0, Qualified: 0, Proposal: 0, Won: 0, Lost: 0 },
  total: 1,
  page_size: 50,
  has_more: { New: false, Contacted: false, Qualified: false, Proposal: false, Won: false, Lost: false },
  board: {
    New: [{
      id: "lead-1",
      name: "Pipe Lead",
      phone: "+919999999999",
      source: "Website",
      pipeline_stage: "New",
      disposition_name: null,
      assigned_to: "a1",
      assigned_name: "Rohan",
      follow_up_at: null,
      last_notes: "Needs site survey",
    }],
    Contacted: [],
    Qualified: [],
    Proposal: [],
    Won: [],
    Lost: [],
  },
}

const countsPayload = {
  stages: board.stages,
  counts: board.counts,
  total: board.total,
}

function mockApi() {
  api.get.mockImplementation((url) => {
    if (url.startsWith("/pipeline/counts")) {
      return Promise.resolve({ data: JSON.parse(JSON.stringify(countsPayload)) })
    }
    if (url.startsWith("/pipeline")) {
      const qs = new URLSearchParams(url.split("?")[1] || "")
      if (qs.get("view") === "list") {
        return Promise.resolve({
          data: {
            stages: board.stages,
            items: board.board.New,
            total: 1,
            page: 1,
            page_size: 50,
            counts: board.counts,
          },
        })
      }
      if (qs.get("stage")) {
        return Promise.resolve({
          data: {
            stage: qs.get("stage"),
            items: [],
            total: 0,
            page: Number(qs.get("page") || 1),
            page_size: 50,
          },
        })
      }
      return Promise.resolve({ data: JSON.parse(JSON.stringify(board)) })
    }
    if (url === "/leads/filter-options") {
      return Promise.resolve({ data: { sources: ["Website"], dispositions: [] } })
    }
    if (url === "/dispositions") {
      return Promise.resolve({
        data: {
          dispositions: [
            { id: "d1", name: "Call Back", active: true, color: "#0EA5E9", requires_acw: false },
          ],
        },
      })
    }
    if (url === "/dashboard/filter-options") {
      return Promise.resolve({ data: { agents: [{ id: "a1", name: "Rohan" }] } })
    }
    if (url === "/leads/lead-1") {
      return Promise.resolve({
        data: {
          lead: board.board.New[0],
          calls: [],
          client: null,
          activity: [],
        },
      })
    }
    if (url.startsWith("/today-calls")) {
      return Promise.resolve({ data: { acw_pending_lead_id: null } })
    }
    return Promise.resolve({ data: {} })
  })
  api.post.mockResolvedValue({ data: { acw: false } })
}

describe("Pipeline workbench", () => {
  beforeEach(() => {
    jest.clearAllMocks()
    __setMockSearchParams(new URLSearchParams())
    useAuth.mockReturnValue({
      can: () => true,
      dataScope: "ALL",
      user: { id: "admin", user_type: "admin" },
    })
    mockApi()
  })

  it("renders filters and kanban card", async () => {
    render(<Pipeline />)
    await waitFor(() => {
      expect(screen.getByTestId("pipeline-filters")).toBeInTheDocument()
      expect(screen.getByTestId("pipeline-card-lead-1")).toBeInTheDocument()
    })
    expect(screen.getByText("Source")).toBeInTheDocument()
    expect(screen.getByText("Disposition")).toBeInTheDocument()
    expect(screen.getByTestId("pipeline-card-last-remarks-lead-1")).toHaveTextContent(
      "Needs site survey",
    )
    expect(api.get).toHaveBeenCalledWith(expect.stringMatching(/^\/pipeline\/counts/))
    expect(api.get).toHaveBeenCalledWith(expect.stringMatching(/^\/pipeline\?.*page_size=50/))
  })

  it("shows last remarks in list view and log dialog", async () => {
    const user = userEvent.setup()
    __setMockSearchParams(new URLSearchParams("view=list"))
    render(<Pipeline />)
    await waitFor(() => {
      expect(screen.getByTestId("pipeline-last-remarks-lead-1")).toBeInTheDocument()
    })
    expect(screen.getByTestId("pipeline-last-remarks-lead-1")).toHaveTextContent(
      "Needs site survey",
    )
    expect(api.get).toHaveBeenCalledWith(expect.stringMatching(/view=list/))

    await user.click(screen.getByTestId("list-log-call-lead-1"))
    const dialog = await screen.findByTestId("pipeline-log-call-dialog")
    expect(within(dialog).getByTestId("log-call-last-remarks")).toHaveTextContent(
      "Needs site survey",
    )
  })

  it("list view shows pagination when total exceeds page", async () => {
    api.get.mockImplementation((url) => {
      if (url.startsWith("/pipeline/counts")) {
        return Promise.resolve({ data: { ...countsPayload, total: 87, counts: { ...board.counts, New: 87 } } })
      }
      if (url.startsWith("/pipeline")) {
        return Promise.resolve({
          data: {
            stages: board.stages,
            items: board.board.New,
            total: 87,
            page: 1,
            page_size: 50,
            counts: board.counts,
          },
        })
      }
      if (url === "/leads/filter-options") {
        return Promise.resolve({ data: { sources: [], dispositions: [] } })
      }
      if (url === "/dispositions") {
        return Promise.resolve({ data: { dispositions: [] } })
      }
      if (url === "/dashboard/filter-options") {
        return Promise.resolve({ data: { agents: [] } })
      }
      return Promise.resolve({ data: {} })
    })
    __setMockSearchParams(new URLSearchParams("view=list"))
    render(<Pipeline />)
    await waitFor(() => {
      expect(screen.getByTestId("table-pagination")).toBeInTheDocument()
    })
    expect(screen.getByTestId("pagination-range")).toHaveTextContent("1–50 of 87")
  })

  it("kanban Call button opens log dialog without opening detail", async () => {
    const user = userEvent.setup()
    render(<Pipeline />)
    await waitFor(() => expect(screen.getByTestId("kanban-call-lead-1")).toBeInTheDocument())
    await user.click(screen.getByTestId("kanban-call-lead-1"))
    expect(await screen.findByTestId("pipeline-log-call-dialog")).toBeInTheDocument()
    expect(screen.queryByTestId("lead-360")).not.toBeInTheDocument()
  })

  it("drop opens move dialog with follow-up; cancel does not post", async () => {
    const user = userEvent.setup()
    const { fireEvent } = require("@testing-library/react")
    render(<Pipeline />)
    await waitFor(() => expect(screen.getByTestId("pipeline-card-lead-1")).toBeInTheDocument())

    const card = screen.getByTestId("pipeline-card-lead-1")
    const col = screen.getByTestId("stage-col-Contacted")
    fireEvent.dragStart(card)
    fireEvent.dragOver(col)
    fireEvent.drop(col)

    const dialog = await screen.findByTestId("pipeline-log-call-dialog")
    expect(within(dialog).getByTestId("move-target-stage")).toHaveTextContent("Contacted")
    const fu = within(dialog).getByTestId("pipeline-followup-input")
    expect(fu).toBeInTheDocument()
    expect(fu.value).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/)
    expect(within(dialog).getByTestId("fu-clear-hint")).toBeInTheDocument()

    await user.click(screen.getByTestId("pipeline-log-cancel"))
    expect(api.post).not.toHaveBeenCalled()
  })

  it("move submit posts /calls/log with pipeline_stage", async () => {
    const user = userEvent.setup()
    const { fireEvent } = require("@testing-library/react")
    render(<Pipeline />)
    await waitFor(() => expect(screen.getByTestId("pipeline-card-lead-1")).toBeInTheDocument())

    fireEvent.dragStart(screen.getByTestId("pipeline-card-lead-1"))
    fireEvent.drop(screen.getByTestId("stage-col-Qualified"))

    const dialog = await screen.findByTestId("pipeline-log-call-dialog")
    await user.selectOptions(within(dialog).getByTestId("pipeline-disposition-select"), "d1")
    fireEvent.change(within(dialog).getByTestId("pipeline-followup-input"), {
      target: { value: "2026-09-10T10:00" },
    })
    await user.click(within(dialog).getByTestId("pipeline-log-submit"))

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/calls/log",
        expect.objectContaining({
          lead_id: "lead-1",
          disposition_id: "d1",
          pipeline_stage: "Qualified",
        }),
      )
    })
  })

  it("card click opens lead 360 with Log Call", async () => {
    const user = userEvent.setup()
    render(<Pipeline />)
    await waitFor(() => expect(screen.getByTestId("pipeline-card-lead-1")).toBeInTheDocument())
    await user.click(screen.getByTestId("pipeline-card-lead-1"))
    await waitFor(() => {
      expect(screen.getByTestId("lead-360")).toBeInTheDocument()
      expect(screen.getByTestId("lead-360-log-call")).toBeInTheDocument()
    })
  })

  it("shows Load more when has_more and appends on click", async () => {
    const user = userEvent.setup()
    const boardWithMore = JSON.parse(JSON.stringify(board))
    boardWithMore.counts.New = 2
    boardWithMore.total = 2
    boardWithMore.has_more.New = true
    api.get.mockImplementation((url) => {
      if (url.startsWith("/pipeline/counts")) {
        return Promise.resolve({
          data: { stages: board.stages, counts: boardWithMore.counts, total: 2 },
        })
      }
      if (url.startsWith("/pipeline")) {
        const qs = new URLSearchParams(url.split("?")[1] || "")
        if (qs.get("stage") === "New") {
          return Promise.resolve({
            data: {
              stage: "New",
              items: [{
                id: "lead-2",
                name: "More Lead",
                phone: "+918888888888",
                pipeline_stage: "New",
                source: "Manual",
              }],
              total: 2,
              page: 2,
              page_size: 50,
            },
          })
        }
        return Promise.resolve({ data: boardWithMore })
      }
      if (url === "/leads/filter-options") {
        return Promise.resolve({ data: { sources: [], dispositions: [] } })
      }
      if (url === "/dispositions") {
        return Promise.resolve({ data: { dispositions: [] } })
      }
      if (url === "/dashboard/filter-options") {
        return Promise.resolve({ data: { agents: [] } })
      }
      return Promise.resolve({ data: {} })
    })

    render(<Pipeline />)
    await waitFor(() => expect(screen.getByTestId("load-more-New")).toBeInTheDocument())
    await user.click(screen.getByTestId("load-more-New"))
    await waitFor(() => {
      expect(screen.getByTestId("pipeline-card-lead-2")).toBeInTheDocument()
    })
  })
})
