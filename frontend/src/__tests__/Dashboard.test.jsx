import { render, screen, waitFor, act } from "@testing-library/react"
import { useAuth } from "@/context/AuthContext"
import api from "@/lib/api"
import Dashboard from "@/pages/Dashboard"

const mockNavigate = jest.fn()

jest.mock("react-router-dom", () => {
  const actual = jest.requireActual("../__mocks__/react-router-dom")
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  }
})

jest.mock("@/context/AuthContext", () => ({
  useAuth: jest.fn(),
}))

jest.mock("@/lib/api", () => ({
  __esModule: true,
  default: {
    get: jest.fn(),
    post: jest.fn(),
  },
}))

jest.mock("@/components/ui/searchable-select", () => ({
  SearchableSelect: ({ testId, label }) => <div data-testid={testId || "searchable"}>{label}</div>,
}))

jest.mock("recharts", () => ({
  ResponsiveContainer: ({ children }) => <div>{children}</div>,
  AreaChart: () => <div data-testid="area-chart" />,
  Area: () => null,
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

const summary = {
  kpis: {
    total_leads: 10,
    active_leads: 7,
    converted_leads: 2,
    conversion_rate: 20,
    unassigned_leads: 3,
    overdue_followups: 1,
    total_calls: 50,
    calls_in_range: 12,
    calls_today: 2,
    avg_call_duration: 45,
    total_clients: 4,
    ftd_clients: 1,
    ledger_credit: 1000,
    ledger_debit: 100,
    net_balance: 900,
  },
  lead_disposition_breakdown: [
    { name: "Interested", label: "Interested", count: 4, pct: 40 },
    { name: "__none__", label: "No response", count: 2, pct: 20 },
  ],
  response_conversion: {
    converted_leads: 2,
    converted_by_response: 2,
    converted_share_pct: 20,
    leads_with_response: 8,
    response_coverage_pct: 80,
    carry_forward_count: 5,
    carry_forward_pct: 50,
    top_response: "Interested",
    top_response_count: 4,
  },
  pipeline_funnel: [{ stage: "New", count: 5, rate_from_prev: 100 }],
  status_breakdown: [{ status: "active", count: 7 }],
  disposition_mix: [{ name: "Interested", value: 4 }],
  source_breakdown: [{ source: "Manual", leads: 5, conversions: 1, conversion_rate: 20 }],
  agent_performance: [{ agent_id: "a1", name: "Rohan", leads: 5, calls: 8, conversions: 1, conversion_rate: 20 }],
  daily_trend: [{ date: "2026-09-01", leads: 1, calls: 2 }],
  calls_trend: [{ date: "09-01", calls: 2 }],
  aging_sla: [{ bucket: "Overdue follow-ups", count: 1 }],
  insights: [{ severity: "warning", title: "Overdue", detail: "1 overdue", href_params: {} }],
}

describe("Dashboard analysis", () => {
  beforeEach(() => {
    jest.clearAllMocks()
    api.get.mockImplementation((url) => {
      if (url.startsWith("/dashboard?")) return Promise.resolve({ data: summary })
      if (url === "/dashboard") return Promise.resolve({ data: summary })
      if (url === "/dashboard/filter-options") {
        return Promise.resolve({
          data: {
            stages: ["New"],
            sources: ["Manual"],
            dispositions: [{ id: "d1", name: "Interested" }],
            agents: [{ id: "a1", name: "Rohan" }],
            statuses: ["active", "inactive", "converted"],
          },
        })
      }
      return Promise.resolve({ data: {} })
    })
  })

  it("renders KPIs for admin ALL scope", async () => {
    useAuth.mockReturnValue({
      user: { id: "admin", user_type: "admin" },
      dataScope: "ALL",
    })

    render(<Dashboard />)

    await waitFor(() => {
      expect(screen.getByTestId("kpi-leads")).toBeInTheDocument()
    })
    expect(screen.getByTestId("kpi-calls")).toBeInTheDocument()
    expect(screen.getByTestId("status-tabs")).toBeInTheDocument()
    expect(screen.getByTestId("responses-overview")).toBeInTheDocument()
    expect(screen.getByTestId("lead-disposition-bars")).toBeInTheDocument()
    expect(screen.getByTestId("response-kpis")).toBeInTheDocument()
  })

  it("hides assignment and agent filters for OWN scope", async () => {
    useAuth.mockReturnValue({
      user: { id: "agent-1", user_type: "caller" },
      dataScope: "OWN",
    })

    render(<Dashboard />)

    await waitFor(() => {
      expect(screen.getByTestId("toggle-filters")).toBeInTheDocument()
    })
    await act(async () => {
      screen.getByTestId("toggle-filters").click()
    })
    await waitFor(() => {
      expect(screen.getByTestId("advanced-filters")).toBeInTheDocument()
    })
    expect(screen.queryByTestId("filter-assignment")).not.toBeInTheDocument()
    expect(screen.queryByTestId("filter-agent")).not.toBeInTheDocument()
  })

  it("hides lead analysis for affiliates", async () => {
    useAuth.mockReturnValue({
      user: { id: "aff-1", user_type: "affiliate" },
      dataScope: "OWN",
    })

    render(<Dashboard />)

    await waitFor(() => {
      expect(screen.getByTestId("kpi-clients")).toBeInTheDocument()
    })
    expect(screen.queryByTestId("status-tabs")).not.toBeInTheDocument()
    expect(screen.queryByTestId("kpi-leads")).not.toBeInTheDocument()
  })
})
