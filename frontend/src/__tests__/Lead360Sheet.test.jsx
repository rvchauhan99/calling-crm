import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { Lead360Sheet } from "@/components/leads/Lead360Sheet"
import api from "@/lib/api"

jest.mock("@/context/AuthContext", () => ({
  useAuth: () => ({ can: () => true }),
}))

jest.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: jest.fn(), post: jest.fn() },
  formatApiError: jest.fn((d) => String(d)),
}))

jest.mock("@/components/ui/searchable-select", () => ({
  SearchableSelect: ({ testId, label, value, onChange, options = [] }) => (
    <div>
      {label && <label htmlFor={testId}>{label}</label>}
      <select id={testId} data-testid={testId} value={value || ""} onChange={(e) => onChange(e.target.value)}>
        <option value="">Select</option>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  ),
}))

jest.mock("sonner", () => ({ toast: { success: jest.fn(), error: jest.fn() } }))

describe("Lead360Sheet", () => {
  beforeEach(() => {
    jest.clearAllMocks()
    api.get.mockImplementation((url) => {
      if (url === "/leads/l1") {
        return Promise.resolve({
          data: {
            lead: {
              id: "l1",
              name: "Ada",
              phone: "+919876543210",
              email: "a@x.com",
              source: "Manual",
              city: "Pune",
              pipeline_stage: "New",
              assigned_name: "Rohan",
              disposition_name: null,
              status: "active",
              follow_up_at: null,
              last_notes: "Good call summary",
              created_at: "2026-09-01T10:00:00.000Z",
              updated_at: "2026-09-01T10:00:00.000Z",
            },
            calls: [{
              id: "c1",
              disposition_name: "Interested",
              created_at: "2026-09-02T10:00:00.000Z",
              notes: "Good call",
              agent_name: "Rohan",
            }],
            client: null,
            activity: [{
              id: "a1",
              action: "log_call",
              entity: "lead",
              actor_name: "Rohan",
              created_at: "2026-09-02T10:00:00.000Z",
              meta: { disposition: "Interested" },
            }],
          },
        })
      }
      if (url === "/dispositions") {
        return Promise.resolve({ data: { dispositions: [] } })
      }
      return Promise.resolve({ data: {} })
    })
  })

  it("renders details, calls, and activity", async () => {
    render(<Lead360Sheet leadId="l1" onClose={() => {}} />)
    await waitFor(() => {
      expect(screen.getByTestId("lead-360")).toBeInTheDocument()
      expect(screen.getByText("Ada")).toBeInTheDocument()
    })
    expect(screen.getByTestId("lead-360-calls")).toHaveTextContent("Interested")
    expect(screen.getByTestId("lead-360-activity")).toHaveTextContent("log_call")
    expect(screen.getByTestId("lead-360-log-call")).toBeInTheDocument()
    expect(screen.getByTestId("lead-360-last-remarks")).toHaveTextContent("Good call summary")
    expect(screen.getByTestId("lead-360-last-remarks")).toHaveTextContent("Last Remarks")
  })

  it("shows empty last remarks when missing", async () => {
    api.get.mockImplementation((url) => {
      if (url === "/leads/l1") {
        return Promise.resolve({
          data: {
            lead: {
              id: "l1",
              name: "Ada",
              phone: "+919876543210",
              source: "Manual",
              pipeline_stage: "New",
              status: "active",
              last_notes: null,
            },
            calls: [],
            client: null,
            activity: [],
          },
        })
      }
      if (url === "/dispositions") {
        return Promise.resolve({ data: { dispositions: [] } })
      }
      return Promise.resolve({ data: {} })
    })
    render(<Lead360Sheet leadId="l1" onClose={() => {}} />)
    await waitFor(() => {
      expect(screen.getByTestId("lead-360-last-remarks")).toHaveTextContent("—")
    })
  })

  it("phone click path is covered via onOpen parent — sheet closes via onClose", async () => {
    const onClose = jest.fn()
    const user = userEvent.setup()
    render(<Lead360Sheet leadId="l1" onClose={onClose} />)
    await waitFor(() => expect(screen.getByText("Ada")).toBeInTheDocument())
    const closeBtn = screen.getByRole("button", { name: /close/i })
    await user.click(closeBtn)
    expect(onClose).toHaveBeenCalled()
  })
})
