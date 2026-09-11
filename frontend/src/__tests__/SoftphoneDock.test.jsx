import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import api from "@/lib/api"
import { SoftphoneDock } from "@/components/softphone/SoftphoneDock"

jest.mock("@/lib/api", () => ({
  __esModule: true,
  default: {
    post: jest.fn(),
  },
  formatApiError: jest.fn((d) => String(d)),
}))

jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn(), message: jest.fn() },
}))

describe("SoftphoneDock", () => {
  beforeEach(() => {
    api.post.mockImplementation((url) => {
      if (url === "/telephony/softphone/session") {
        return Promise.resolve({
          data: {
            token: "mock-token",
            url: "mock://local",
            room_name: "room-1",
            identity: "agent-1",
            provider: "mock",
            mock: true,
          },
        })
      }
      if (url === "/telephony/originate") {
        return Promise.resolve({
          data: { provider_call_id: "mock-call-1", status: "ringing", mock: true, room_name: "room-1" },
        })
      }
      if (url === "/telephony/hangup") return Promise.resolve({ data: { ok: true } })
      if (url === "/telephony/webhooks/mock") return Promise.resolve({ data: { ok: true } })
      return Promise.resolve({ data: {} })
    })
  })

  it("dials and hangs up (happy path)", async () => {
    const user = userEvent.setup()
    const onEnded = jest.fn()
    render(
      <SoftphoneDock
        open
        leadId="lead-1"
        leadPhone="+919811111111"
        leadName="Test Lead"
        onEnded={onEnded}
      />,
    )
    expect(screen.getByTestId("softphone-dock")).toBeInTheDocument()
    await user.click(screen.getByTestId("softphone-dial"))
    await waitFor(() => {
      expect(screen.getByTestId("softphone-status")).not.toHaveTextContent("idle")
    })
    expect(screen.getByTestId("softphone-mock-badge")).toBeInTheDocument()
    await user.click(screen.getByTestId("softphone-hangup"))
    await waitFor(() => expect(onEnded).toHaveBeenCalled())
  })

  it("shows idle when closed", () => {
    const { container } = render(
      <SoftphoneDock open={false} leadPhone="+9198" leadName="X" />,
    )
    expect(container.querySelector('[data-testid="softphone-dock"]')).toBeNull()
  })
})
