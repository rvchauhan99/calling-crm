import { render, screen, waitFor, fireEvent } from "@testing-library/react"
import { useAuth } from "@/context/AuthContext"
import api from "@/lib/api"
import IpAccess from "@/pages/IpAccess"

jest.mock("@/context/AuthContext", () => ({
  useAuth: jest.fn(),
}))

jest.mock("@/lib/api", () => ({
  __esModule: true,
  default: {
    get: jest.fn(),
    post: jest.fn(),
    put: jest.fn(),
    delete: jest.fn(),
  },
  API: "http://localhost:8000/api",
  getToken: jest.fn(() => "test-token"),
  formatApiError: jest.fn((detail) => String(detail)),
}))

jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn(), message: jest.fn() },
}))

const mockRows = [
  {
    id: "ip-1",
    label: "Main office",
    cidr: "203.0.113.0/24",
    active: true,
  },
]

describe("IpAccess page", () => {
  beforeEach(() => {
    jest.clearAllMocks()
    useAuth.mockReturnValue({
      can: () => true,
      dataScope: "ALL",
      user: { id: "admin-1", user_type: "admin" },
    })
    api.get.mockImplementation((url) => {
      if (url === "/ip-access/my-ip") {
        return Promise.resolve({ data: { ip: "203.0.113.45" } })
      }
      return Promise.resolve({ data: { ip_access: mockRows, allow_all: false } })
    })
    api.post.mockResolvedValue({
      data: { ip_access: { id: "ip-new", cidr: "198.51.100.1/32", label: "Home" } },
    })
  })

  it("lists entries and saves a new one", async () => {
    render(<IpAccess />)

    await waitFor(() => {
      expect(screen.getByTestId("ip-access-page")).toBeInTheDocument()
      expect(screen.getByTestId("ip-access-row-ip-1")).toBeInTheDocument()
      expect(screen.getByTestId("ip-access-my-ip-value")).toHaveTextContent("203.0.113.45")
    })

    fireEvent.click(screen.getByTestId("new-ip-access-btn"))
    await waitFor(() => {
      expect(screen.getByTestId("ip-access-dialog")).toBeInTheDocument()
    })

    fireEvent.change(screen.getByTestId("ip-access-label"), {
      target: { value: "Home" },
    })
    fireEvent.change(screen.getByTestId("ip-access-cidr"), {
      target: { value: "198.51.100.1" },
    })
    fireEvent.click(screen.getByTestId("save-ip-access-btn"))

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/ip-access", expect.objectContaining({
        cidr: "198.51.100.1",
        label: "Home",
        active: true,
      }))
    })
  })

  it("shows allow-all banner when empty active list", async () => {
    api.get.mockImplementation((url) => {
      if (url === "/ip-access/my-ip") {
        return Promise.resolve({ data: { ip: "127.0.0.1" } })
      }
      return Promise.resolve({ data: { ip_access: [], allow_all: true } })
    })
    render(<IpAccess />)
    await waitFor(() => {
      expect(screen.getByTestId("ip-access-allow-all-banner")).toBeInTheDocument()
      expect(screen.getByTestId("ip-access-empty")).toBeInTheDocument()
    })
  })

  it("hides create when RBAC denies ip_access:create", async () => {
    useAuth.mockReturnValue({
      can: (perm) => perm !== "ip_access:create",
      dataScope: "ALL",
      user: { id: "agent-1" },
    })
    render(<IpAccess />)
    await waitFor(() => {
      expect(screen.getByTestId("ip-access-page")).toBeInTheDocument()
    })
    expect(screen.queryByTestId("new-ip-access-btn")).not.toBeInTheDocument()
  })
})
