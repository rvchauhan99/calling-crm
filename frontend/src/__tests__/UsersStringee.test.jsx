import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import api from "@/lib/api"
import Users from "@/pages/Users"

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

jest.mock("@/context/AuthContext", () => ({
  useAuth: () => ({
    can: () => true,
  }),
}))

jest.mock("@/components/ui/searchable-select", () => ({
  SearchableSelect: ({ testId, value, onChange, options = [] }) => (
    <select
      data-testid={testId}
      value={value || ""}
      onChange={(e) => onChange?.(e.target.value)}
    >
      {(options || []).map((o) => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  ),
}))

jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}))

describe("Users Stringee fields", () => {
  beforeEach(() => {
    jest.clearAllMocks()
    api.get.mockImplementation((url = "") => {
      if (String(url).includes("/users") || String(url).startsWith("users")) {
        return Promise.resolve({
          data: {
            users: [{
              id: "u1",
              name: "Caller One",
              email: "c1@example.com",
              role_id: "r1",
              role_name: "Agent",
              user_type: "caller",
              daily_quota: 10,
              active: true,
              stringee_user_id: "agent_c1",
              stringee_enabled: true,
            }],
          },
        })
      }
      if (String(url).includes("/roles") || String(url) === "/roles") {
        return Promise.resolve({ data: { roles: [{ id: "r1", name: "Agent" }] } })
      }
      return Promise.resolve({ data: { users: [], roles: [] } })
    })
    api.post.mockResolvedValue({ data: { user: { id: "u2" } } })
  })

  it("shows Stringee fields for caller create (happy path)", async () => {
    const user = userEvent.setup()
    render(<Users />)
    await waitFor(() => expect(screen.getByTestId("new-user-btn")).toBeInTheDocument())
    await waitFor(() => expect(screen.getByTestId("user-row-u1")).toBeInTheDocument())
    await user.click(screen.getByTestId("new-user-btn"))
    await waitFor(() => expect(screen.getByTestId("user-dialog")).toBeInTheDocument())
    expect(screen.getByTestId("user-stringee-id")).toBeInTheDocument()
    expect(screen.getByTestId("user-stringee-enabled")).toBeInTheDocument()
    await user.type(screen.getByTestId("user-name"), "New Caller")
    await user.type(screen.getByTestId("user-email"), "new@example.com")
    await user.type(screen.getByTestId("user-password"), "Pass@1234")
    await user.clear(screen.getByTestId("user-stringee-id"))
    await user.type(screen.getByTestId("user-stringee-id"), "agent_new")
    await user.click(screen.getByTestId("save-user-btn"))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/users", expect.objectContaining({
      stringee_user_id: "agent_new",
      user_type: "caller",
    })))
  })
})
