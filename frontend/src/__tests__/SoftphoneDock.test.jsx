import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import api from "@/lib/api"
import { SoftphoneDock } from "@/components/softphone/SoftphoneDock"
import { loadStringeeSdk } from "@/lib/stringeeSdk"

jest.mock("@/lib/api", () => ({
  __esModule: true,
  default: {
    post: jest.fn(),
  },
  formatApiError: jest.fn((d) => String(d)),
}))

jest.mock("@/lib/stringeeSdk", () => ({
  loadStringeeSdk: jest.fn(),
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
          data: { provider_call_id: "mock-call-1", status: "ringing", mock: true, room_name: "room-1", call_id: "c1" },
        })
      }
      if (url === "/telephony/hangup") return Promise.resolve({ data: { ok: true } })
      if (url === "/telephony/webhooks/mock") return Promise.resolve({ data: { ok: true } })
      if (url === "/telephony/stringee/bind-call") return Promise.resolve({ data: { ok: true } })
      if (url === "/telephony/stringee/reconcile") {
        return Promise.resolve({ data: { ok: true, reconciled: false, status: "ringing" } })
      }
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

  it("stringee web_sdk path shows badge and uses SDK dial", async () => {
    const user = userEvent.setup()
    const makeCall = jest.fn((cb) => cb({ r: 0, callId: "call-vn-1-SDK" }))
    const hangup = jest.fn((cb) => cb && cb())
    const connect = jest.fn()
    const on = jest.fn((evt, handler) => {
      if (evt === "authen") {
        setTimeout(() => handler({ r: 0, userId: "agent_se" }), 0)
      }
    })
    loadStringeeSdk.mockResolvedValue({
      StringeeClient: jest.fn(() => ({ connect, on, disconnect: jest.fn() })),
      StringeeCall: jest.fn(() => ({
        on: jest.fn(),
        makeCall,
        hangup,
        mute: jest.fn(),
        callId: "call-vn-1-SDK",
        customData: "",
      })),
      StringeeUtil: {},
    })

    api.post.mockImplementation((url) => {
      if (url === "/telephony/softphone/session") {
        return Promise.resolve({
          data: {
            token: "se-jwt",
            url: "https://api.stringee.com",
            room_name: "room-se",
            identity: "agent_se",
            provider: "stringee",
            mock: false,
            dial_mode: "web_sdk",
            stringee_user_id: "agent_se",
            from_number: "+91111",
            from_numbers: [{ e164: "+91111", label: "Main", is_default: true }],
          },
        })
      }
      if (url === "/telephony/originate") {
        return Promise.resolve({
          data: { provider_call_id: "stringee-pending-abc", status: "ringing", mock: false, call_id: "crm1" },
        })
      }
      if (url === "/telephony/stringee/bind-call") return Promise.resolve({ data: { ok: true } })
      if (url === "/telephony/hangup") return Promise.resolve({ data: { ok: true } })
      return Promise.resolve({ data: {} })
    })

    render(
      <SoftphoneDock open leadId="L1" leadPhone="+919812345678" leadName="SE Lead" />,
    )
    await user.click(screen.getByTestId("softphone-dial"))
    await waitFor(() => {
      expect(screen.getByTestId("softphone-stringee-badge")).toBeInTheDocument()
    })
    expect(makeCall).toHaveBeenCalled()
  })

  it("stringee pcc path originates without SDK and shows CLI picker", async () => {
    const user = userEvent.setup()
    loadStringeeSdk.mockClear()

    api.post.mockImplementation((url, body) => {
      if (url === "/telephony/softphone/session") {
        return Promise.resolve({
          data: {
            token: "",
            url: "https://icc-api.stringee.com",
            room_name: "room-pcc",
            identity: "nisha_agent",
            provider: "stringee",
            mock: false,
            dial_mode: "pcc",
            stringee_user_id: "nisha_agent",
            from_number: "+917971701163",
            from_numbers: [
              { e164: "+917971701163", label: "DID 163", is_default: true },
              { e164: "+917971701164", label: "DID 164", is_default: false },
            ],
          },
        })
      }
      if (url === "/telephony/originate") {
        expect(body.from_number).toBeTruthy()
        return Promise.resolve({
          data: {
            provider_call_id: "stringee-pcc-abc123",
            status: "ringing",
            mock: false,
            call_id: "crm-pcc-1",
            dial_mode: "pcc",
            from_number: body.from_number,
          },
        })
      }
      if (url === "/telephony/stringee/reconcile") {
        return Promise.resolve({
          data: { ok: true, reconciled: true, status: "ringing", call_id: "crm-pcc-1" },
        })
      }
      if (url === "/telephony/hangup") return Promise.resolve({ data: { ok: true } })
      return Promise.resolve({ data: {} })
    })

    render(
      <SoftphoneDock open leadId="L2" leadPhone="+919800011122" leadName="PCC Lead" />,
    )

    await waitFor(() => {
      expect(screen.getByTestId("softphone-cli-select")).toBeInTheDocument()
    })

    await user.click(screen.getByTestId("softphone-dial"))
    await waitFor(() => {
      expect(screen.getByTestId("softphone-stringee-badge")).toHaveTextContent("Answer in StringeeX")
    })
    expect(loadStringeeSdk).not.toHaveBeenCalled()
    expect(api.post).toHaveBeenCalledWith(
      "/telephony/originate",
      expect.objectContaining({
        to_number: "+919800011122",
        from_number: expect.any(String),
      }),
    )
  })
})
