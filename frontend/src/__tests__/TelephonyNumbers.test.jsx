import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import api from "@/lib/api"
import TelephonyNumbers from "@/pages/TelephonyNumbers"

jest.mock("@/context/AuthContext", () => ({
  useAuth: () => ({ can: () => true }),
}))

jest.mock("@/lib/api", () => ({
  __esModule: true,
  default: {
    get: jest.fn(),
    post: jest.fn(),
    put: jest.fn(),
    delete: jest.fn(),
  },
  formatApiError: jest.fn((d) => String(d)),
}))

jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}))

const mockNumbers = {
  numbers: [{
    id: "did1",
    e164: "+919876543210",
    label: "Main",
    active: true,
    is_default: true,
  }],
}

const inactiveStatus = {
  adapter: "mock",
  active_calls: 0,
  max_concurrent: 5,
  did: "",
  livekit_configured: false,
  enabled: false,
  ui_enabled: false,
  inactive_reason: "Complete Udyam/Plivo registration and set LIVEKIT_* keys",
}

const activeStatus = {
  adapter: "plivo_livekit",
  active_calls: 0,
  max_concurrent: 5,
  did: "+9198",
  livekit_configured: true,
  enabled: true,
  ui_enabled: true,
  inactive_reason: null,
}

describe("TelephonyNumbers", () => {
  beforeEach(() => {
    jest.clearAllMocks()
    api.get.mockImplementation((url) => {
      if (url === "/telephony/numbers") {
        return Promise.resolve({ data: mockNumbers })
      }
      if (url === "/telephony/status") {
        return Promise.resolve({ data: inactiveStatus })
      }
      return Promise.resolve({ data: {} })
    })
  })

  it("shows inactive banner and locks mutations when ui_enabled is false", async () => {
    render(<TelephonyNumbers />)
    expect(await screen.findByTestId("telephony-numbers-page")).toBeInTheDocument()
    expect(screen.getByTestId("telephony-inactive-banner")).toHaveTextContent(/inactive/i)
    expect(screen.getByTestId("telephony-status-banner")).toHaveTextContent("mock")
    expect(screen.getByText("+919876543210")).toBeInTheDocument()
    expect(screen.queryByTestId("telephony-add-number")).not.toBeInTheDocument()
    expect(screen.queryByTestId("telephony-ivr-did1")).not.toBeInTheDocument()
    expect(screen.getByTestId("telephony-row-locked")).toBeInTheDocument()
  })

  it("opens add dialog when telephony is enabled", async () => {
    api.get.mockImplementation((url) => {
      if (url === "/telephony/numbers") {
        return Promise.resolve({ data: mockNumbers })
      }
      if (url === "/telephony/status") {
        return Promise.resolve({ data: activeStatus })
      }
      return Promise.resolve({ data: {} })
    })
    const user = userEvent.setup()
    render(<TelephonyNumbers />)
    await screen.findByTestId("telephony-numbers-page")
    await user.click(screen.getByTestId("telephony-add-number"))
    expect(await screen.findByTestId("telephony-number-dialog")).toBeInTheDocument()
    expect(screen.getByTestId("telephony-e164")).toBeInTheDocument()
  })

  it("opens IVR editor when telephony is enabled", async () => {
    const user = userEvent.setup()
    api.get.mockImplementation((url) => {
      if (url === "/telephony/numbers") {
        return Promise.resolve({
          data: { numbers: [{ id: "did1", e164: "+919876543210", label: "Main", active: true }] },
        })
      }
      if (url === "/telephony/status") {
        return Promise.resolve({ data: activeStatus })
      }
      if (url === "/telephony/ivr/did1") {
        return Promise.resolve({
          data: {
            greeting_text: "Hello",
            menu: [{ digit: "1", label: "Sales", action: "queue", target: "sales" }],
            missed_create_lead: true,
            active: true,
          },
        })
      }
      return Promise.resolve({ data: {} })
    })
    render(<TelephonyNumbers />)
    await screen.findByTestId("telephony-ivr-did1")
    await user.click(screen.getByTestId("telephony-ivr-did1"))
    expect(await screen.findByTestId("telephony-ivr-dialog")).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByTestId("telephony-ivr-greeting")).toHaveValue("Hello")
    })
  })
})
