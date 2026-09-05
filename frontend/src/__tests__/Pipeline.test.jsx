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

describe("Pipeline workbench", () => {
  beforeEach(() => {
    jest.clearAllMocks()
    __setMockSearchParams(new URLSearchParams())
    useAuth.mockReturnValue({
      can: () => true,
      dataScope: "ALL",
      user: { id: "admin", user_type: "admin" },
    })
    api.get.mockImplementation((url) => {
      if (url.startsWith("/pipeline")) {
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
      if (url === "/today-calls") {
        return Promise.resolve({ data: { acw_pending_lead_id: null } })
      }
      return Promise.resolve({ data: {} })
    })
    api.post.mockResolvedValue({ data: { acw: false } })
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

    await user.click(screen.getByTestId("list-log-call-lead-1"))
    const dialog = await screen.findByTestId("pipeline-log-call-dialog")
    expect(within(dialog).getByTestId("log-call-last-remarks")).toHaveTextContent(
      "Needs site survey",
    )
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
    // Move mode / Call Back already prefills follow-up; set explicitly for determinism
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
})
