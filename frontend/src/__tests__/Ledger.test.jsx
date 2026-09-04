import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import Ledger from "@/pages/Ledger"
import api from "@/lib/api"

jest.mock("@/context/AuthContext", () => ({
  useAuth: () => ({ can: () => true }),
}))

jest.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: jest.fn(), post: jest.fn() },
  API: "http://localhost:8000/api",
  getToken: () => "t",
  formatApiError: (d) => String(d),
}))

jest.mock("@/components/ui/searchable-select", () => ({
  SearchableSelect: ({ testId, label, options = [] }) => (
    <div data-testid={testId}>
      {label && <span>{label}</span>}
      <ul>
        {options.map((o) => (
          <li key={o.value}>{o.label}</li>
        ))}
      </ul>
    </div>
  ),
}))

jest.mock("sonner", () => ({ toast: { success: jest.fn(), error: jest.fn() } }))

describe("Ledger client picker", () => {
  beforeEach(() => {
    jest.clearAllMocks()
    api.get.mockImplementation((url) => {
      if (url.startsWith("/ledger?")) {
        return Promise.resolve({
          data: {
            entries: [],
            total: 0,
            page: 1,
            page_size: 40,
            totals: { credit: 0, debit: 0 },
          },
        })
      }
      if (url.startsWith("/clients?")) {
        return Promise.resolve({
          data: {
            clients: [
              { id: "c1", name: "Alpha", phone: "+919111111111", balance: 100, status: "active" },
              { id: "c2", name: "Beta", phone: "+919222222222", balance: 0, status: "active" },
            ],
          },
        })
      }
      return Promise.resolve({ data: {} })
    })
  })

  it("shows a single Client label and phone in options", async () => {
    const user = userEvent.setup()
    render(<Ledger />)
    await waitFor(() => expect(screen.getByTestId("new-entry-btn")).toBeInTheDocument())
    await user.click(screen.getByTestId("new-entry-btn"))
    await waitFor(() => {
      expect(screen.getByTestId("ledger-client")).toBeInTheDocument()
    })
    const labels = screen.getAllByText("Client")
    expect(labels).toHaveLength(1)
    expect(screen.getByTestId("ledger-client")).toHaveTextContent("+919111111111")
  })
})
