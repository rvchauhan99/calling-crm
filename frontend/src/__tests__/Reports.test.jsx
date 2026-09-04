import { render, screen, waitFor, act } from "@testing-library/react"
import { useAuth } from "@/context/AuthContext"
import api from "@/lib/api"
import Reports from "@/pages/Reports"

const mockNavigate = jest.fn()

jest.mock("react-router-dom", () => ({
  useNavigate: () => mockNavigate,
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
}))

jest.mock("@/components/ui/searchable-select", () => ({
  SearchableSelect: ({ testId, label }) => <div data-testid={testId || "searchable"}>{label}</div>,
}))

jest.mock("recharts", () => ({
  ResponsiveContainer: ({ children }) => <div>{children}</div>,
  BarChart: () => <div data-testid="bar-chart" />,
  Bar: () => null,
  PieChart: () => <div data-testid="pie-chart" />,
  Pie: () => null,
  Cell: () => null,
  XAxis: () => null,
  YAxis: () => null,
  CartesianGrid: () => null,
  Tooltip: () => null,
  Legend: () => null,
}))

const callerPayload = {
  rows: [{
    agent_id: "a1",
    name: "Rohan",
    calls: 10,
    connected: 6,
    connect_rate: 60,
    leads: 5,
    conversions: 1,
    conversion_rate: 20,
    top_disposition: "Interested",
    converted_responses: 1,
    disposition_breakdown: [{ name: "Interested", count: 6 }],
  }],
  summary: {
    total_calls: 10,
    total_connected: 6,
    connect_rate: 60,
    total_leads: 5,
    total_conversions: 1,
    conversion_rate: 20,
    responses_logged: 10,
    converted_responses: 1,
    converted_response_share: 10,
  },
  disposition_breakdown: [
    { name: "Interested", count: 6, pct: 60 },
    { name: "Call Back", count: 4, pct: 40 },
  ],
  from: "2026-09-01",
  to: "2026-09-04",
}

const affiliatePayload = {
  rows: [{ affiliate_id: "af1", name: "Partner", clients: 3, ftd: 1, ftd_rate: 33.3, total_balance: 500 }],
  summary: { total_clients: 3, total_ftd: 1, ftd_rate: 33.3, total_balance: 500 },
}

describe("Reports page", () => {
  beforeEach(() => {
    jest.clearAllMocks()
    api.get.mockImplementation((url) => {
      if (url.startsWith("/reports/caller")) return Promise.resolve({ data: callerPayload })
      if (url.startsWith("/reports/affiliate")) return Promise.resolve({ data: affiliatePayload })
      if (url.startsWith("/reports/company")) {
        return Promise.resolve({
          data: {
            rows: [{ source: "Manual", leads: 4, conversions: 1, conversion_rate: 25 }],
            summary: {
              total_leads: 4,
              total_conversions: 1,
              conversion_rate: 25,
              responses_logged: 8,
              converted_responses: 1,
              converted_response_share: 12.5,
              connect_rate: 50,
            },
            disposition_breakdown: [
              { name: "Interested", count: 5, pct: 62.5, connected: 4, conversions: 0 },
              { name: "Converted", count: 1, pct: 12.5, connected: 1, conversions: 1 },
            ],
          },
        })
      }
      if (url === "/dashboard/filter-options") {
        return Promise.resolve({
          data: { agents: [{ id: "a1", name: "Rohan" }], sources: ["Manual"] },
        })
      }
      return Promise.resolve({ data: {} })
    })
  })

  it("renders KPIs and caller tab for admin", async () => {
    useAuth.mockReturnValue({
      can: (p) => p === "reports:export",
      user: { id: "admin", user_type: "admin" },
    })

    render(<Reports />)

    await waitFor(() => {
      expect(screen.getByTestId("caller-kpis")).toBeInTheDocument()
    })
    expect(screen.getByTestId("kpi-calls")).toBeInTheDocument()
    expect(screen.getByTestId("tab-caller")).toBeInTheDocument()
    expect(screen.getByTestId("tab-company")).toBeInTheDocument()
  })

  it("shows only Affiliate tab for affiliate users", async () => {
    useAuth.mockReturnValue({
      can: () => false,
      user: { id: "aff-1", user_type: "affiliate" },
    })

    render(<Reports />)

    await waitFor(() => {
      expect(screen.getByTestId("tab-affiliate")).toBeInTheDocument()
    })
    expect(screen.queryByTestId("tab-caller")).not.toBeInTheDocument()
    expect(screen.queryByTestId("tab-company")).not.toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByTestId("affiliate-kpis")).toBeInTheDocument()
    })
  })

  it("Apply sends from/to query params", async () => {
    useAuth.mockReturnValue({
      can: () => false,
      user: { id: "admin", user_type: "admin" },
    })

    render(<Reports />)

    await waitFor(() => {
      expect(screen.getByTestId("reports-apply")).toBeInTheDocument()
    })

    api.get.mockClear()
    await act(async () => {
      screen.getByTestId("reports-apply").click()
    })

    await waitFor(() => {
      const calls = api.get.mock.calls.map((c) => c[0])
      expect(calls.some((u) => typeof u === "string" && u.includes("/reports/caller?") && u.includes("from="))).toBe(true)
    })
  })
})
