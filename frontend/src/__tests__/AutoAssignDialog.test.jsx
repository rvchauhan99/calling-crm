import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import api from "@/lib/api"
import { AutoAssignDialog } from "@/components/leads/AutoAssignDialog"

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

const previewData = {
  assigned: 5,
  requested: 5,
  available_in_pool: 20,
  by_agent: [
    {
      agent_id: "a1",
      agent_name: "Amy",
      assigned: 2,
      quota: 500,
      assigned_today_before: 150,
      slots_available: 350,
    },
    {
      agent_id: "a2",
      agent_name: "Bob",
      assigned: 2,
      quota: 500,
      assigned_today_before: 150,
      slots_available: 350,
    },
    {
      agent_id: "a3",
      agent_name: "Cara",
      assigned: 1,
      quota: 500,
      assigned_today_before: 150,
      slots_available: 350,
    },
  ],
}

describe("AutoAssignDialog", () => {
  beforeEach(() => {
    jest.clearAllMocks()
    api.get.mockResolvedValue({ data: previewData })
    api.post.mockResolvedValue({
      data: { ...previewData, assigned: 5, by_agent: previewData.by_agent },
    })
  })

  it("renders equal preview counts and posts allocations on confirm", async () => {
    const onComplete = jest.fn()
    render(
      <AutoAssignDialog open onOpenChange={jest.fn()} onComplete={onComplete} />,
    )

    await waitFor(() => {
      expect(screen.getByTestId("auto-assign-agent-count-a1")).toHaveValue(2)
    })
    expect(screen.getByTestId("auto-assign-agent-count-a2")).toHaveValue(2)
    expect(screen.getByTestId("auto-assign-agent-count-a3")).toHaveValue(1)
    expect(screen.getByTestId("confirm-auto-assign-btn")).toHaveTextContent("Assign 5 leads")

    await userEvent.click(screen.getByTestId("confirm-auto-assign-btn"))

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/leads/auto-assign", {
        allocations: [
          { agent_id: "a1", count: 2 },
          { agent_id: "a2", count: 2 },
          { agent_id: "a3", count: 1 },
        ],
      })
    })
    expect(onComplete).toHaveBeenCalled()
  })

  it("clamps per-agent input to slots_available", async () => {
    render(
      <AutoAssignDialog open onOpenChange={jest.fn()} onComplete={jest.fn()} />,
    )
    const input = await screen.findByTestId("auto-assign-agent-count-a1")
    await userEvent.clear(input)
    await userEvent.type(input, "999")
    expect(input).toHaveValue(350)
    expect(screen.getByTestId("confirm-auto-assign-btn")).toHaveTextContent("Assign 353 leads")
  })

  it("disables confirm when all agent counts are zero", async () => {
    api.get.mockResolvedValue({
      data: {
        assigned: 0,
        requested: null,
        available_in_pool: 0,
        by_agent: [],
      },
    })
    render(
      <AutoAssignDialog open onOpenChange={jest.fn()} onComplete={jest.fn()} />,
    )
    await waitFor(() => {
      expect(screen.getByText(/No agent slots available/i)).toBeInTheDocument()
    })
    expect(screen.getByTestId("confirm-auto-assign-btn")).toBeDisabled()
  })

  it("resets equal defaults when max_leads changes", async () => {
    api.get
      .mockResolvedValueOnce({ data: previewData })
      .mockResolvedValueOnce({
        data: {
          assigned: 3,
          requested: 3,
          available_in_pool: 20,
          by_agent: [
            { ...previewData.by_agent[0], assigned: 1 },
            { ...previewData.by_agent[1], assigned: 1 },
            { ...previewData.by_agent[2], assigned: 1 },
          ],
        },
      })

    render(
      <AutoAssignDialog open onOpenChange={jest.fn()} onComplete={jest.fn()} />,
    )
    await screen.findByTestId("auto-assign-agent-count-a1")
    const maxInput = screen.getByTestId("auto-assign-count")
    await userEvent.clear(maxInput)
    await userEvent.type(maxInput, "3")

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith("/leads/auto-assign/preview?max_leads=3")
    })
    await waitFor(() => {
      expect(screen.getByTestId("auto-assign-agent-count-a1")).toHaveValue(1)
    })
  })
})
