import { render, screen, waitFor } from "@testing-library/react"
import { useAuth } from "@/context/AuthContext"
import api from "@/lib/api"
import Leads from "@/pages/Leads"
import { __setMockSearchParams } from "react-router-dom"

jest.mock("@/components/leads/SourceSelect", () => ({
  SourceSelect: () => null,
}))

jest.mock("@/components/ui/searchable-select", () => ({
  SearchableSelect: () => null,
}))

jest.mock("@/components/leads/AutoAssignDialog", () => ({
  AutoAssignDialog: () => null,
}))

jest.mock("@/components/leads/PhoneField", () => ({
  PhoneField: () => null,
}))

jest.mock("@/components/leads/EmailField", () => ({
  EmailField: () => null,
}))

jest.mock("@/context/AuthContext", () => ({
  useAuth: jest.fn(),
}))

jest.mock("@/lib/api", () => ({
  __esModule: true,
  default: {
    get: jest.fn(),
    post: jest.fn(),
  },
  API: "http://localhost:8000/api",
  getToken: jest.fn(() => "test-token"),
  formatApiError: jest.fn((detail) => String(detail)),
}))

const mockLeadsResponse = {
  leads: [{
    id: "lead-1",
    name: "Test Lead",
    phone: "+919876543210",
    source: "Manual",
    status: "active",
    pipeline_stage: "New",
    assigned_to: "agent-1",
    assigned_name: "Rohan",
    last_notes: "Interested in solar package",
  }],
  total: 1,
  page: 1,
  page_size: 25,
}

function mockApiForLeads() {
  api.get.mockImplementation((url) => {
    if (url.startsWith("/leads?")) {
      return Promise.resolve({ data: mockLeadsResponse })
    }
    if (url === "/leads/tab-counts") {
      return Promise.resolve({ data: { unassigned: 0, assigned: 1 } })
    }
    if (url === "/leads/filter-options") {
      return Promise.resolve({ data: { stages: ["New"], dispositions: [] } })
    }
    return Promise.resolve({ data: {} })
  })
}

describe("Leads role visibility", () => {
  beforeEach(() => {
    jest.clearAllMocks()
    __setMockSearchParams(new URLSearchParams())
    mockApiForLeads()
  })

  it("hides assignment tabs for OWN-scoped agents", async () => {
    useAuth.mockReturnValue({
      can: () => false,
      dataScope: "OWN",
      user: { id: "agent-1", user_type: "caller" },
    })

    render(<Leads />)

    await waitFor(() => {
      expect(screen.getByTestId("leads-page")).toBeInTheDocument()
      expect(screen.getByTestId("lead-row-lead-1")).toBeInTheDocument()
    })

    expect(screen.queryByTestId("tab-unassigned")).not.toBeInTheDocument()
    expect(screen.queryByTestId("tab-assigned")).not.toBeInTheDocument()
  })

  it("shows labeled filters and clear when filters active", async () => {
    useAuth.mockReturnValue({
      can: () => false,
      dataScope: "OWN",
      user: { id: "agent-1", user_type: "caller" },
    })
    __setMockSearchParams(new URLSearchParams("status=active&sort=name_asc"))

    render(<Leads />)

    await waitFor(() => {
      expect(screen.getByTestId("leads-filters")).toBeInTheDocument()
    })
    expect(screen.getByText("Status")).toBeInTheDocument()
    expect(screen.getByText("Sort")).toBeInTheDocument()
    expect(screen.getByTestId("clear-all-filters")).toBeInTheDocument()
  })

  it("shows assignment tabs for ALL-scoped users", async () => {
    useAuth.mockReturnValue({
      can: (perm) => perm === "leads:assign",
      dataScope: "ALL",
      user: { id: "admin-1", user_type: "admin" },
    })

    api.get.mockImplementation((url) => {
      if (url.startsWith("/leads?")) {
        return Promise.resolve({ data: mockLeadsResponse })
      }
      if (url === "/leads/tab-counts") {
        return Promise.resolve({ data: { unassigned: 5, assigned: 10 } })
      }
      if (url === "/leads/filter-options") {
        return Promise.resolve({ data: { stages: ["New"], dispositions: [] } })
      }
      if (url === "/leads/assignable-callers") {
        return Promise.resolve({ data: { users: [] } })
      }
      return Promise.resolve({ data: {} })
    })

    render(<Leads />)

    await waitFor(() => {
      expect(screen.getByTestId("tab-unassigned")).toBeInTheDocument()
    })

    expect(screen.getByTestId("tab-assigned")).toBeInTheDocument()
  })

  it("shows last remarks column for leads", async () => {
    useAuth.mockReturnValue({
      can: () => false,
      dataScope: "OWN",
      user: { id: "agent-1", user_type: "caller" },
    })

    render(<Leads />)

    await waitFor(() => {
      expect(screen.getByTestId("lead-last-remarks-lead-1")).toBeInTheDocument()
    })
    expect(screen.getByText("Last Remarks")).toBeInTheDocument()
    expect(screen.getByTestId("lead-last-remarks-lead-1")).toHaveTextContent(
      "Interested in solar package",
    )
  })
})
