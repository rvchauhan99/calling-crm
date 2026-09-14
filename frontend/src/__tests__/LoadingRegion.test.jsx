import { render, screen } from "@testing-library/react"
import { LoadingOverlay, LoadingRegion, TableSkeleton } from "@/components/common"

describe("LoadingRegion", () => {
  it("shows skeleton on initial load", () => {
    render(
      <LoadingRegion
        loading
        hasData={false}
        testId="demo-region"
        skeleton={<TableSkeleton testId="demo-skeleton" />}
      >
        <div data-testid="demo-content">content</div>
      </LoadingRegion>,
    )
    expect(screen.getByTestId("demo-skeleton")).toBeInTheDocument()
    expect(screen.queryByTestId("demo-content")).not.toBeInTheDocument()
  })

  it("shows overlay while refetching over existing data", () => {
    render(
      <LoadingRegion loading hasData testId="demo-region" overlayTestId="demo-overlay">
        <div data-testid="demo-content">content</div>
      </LoadingRegion>,
    )
    expect(screen.getByTestId("demo-content")).toBeInTheDocument()
    expect(screen.getByTestId("demo-overlay")).toBeInTheDocument()
    expect(screen.getByTestId("demo-overlay")).toHaveTextContent(/Updating/)
  })

  it("renders children without overlay when idle", () => {
    render(
      <LoadingRegion loading={false} hasData testId="demo-region" overlayTestId="demo-overlay">
        <div data-testid="demo-content">content</div>
      </LoadingRegion>,
    )
    expect(screen.getByTestId("demo-content")).toBeInTheDocument()
    expect(screen.queryByTestId("demo-overlay")).not.toBeInTheDocument()
  })
})

describe("LoadingOverlay", () => {
  it("exposes busy status", () => {
    render(<LoadingOverlay testId="busy" label="Working…" />)
    const el = screen.getByTestId("busy")
    expect(el).toHaveAttribute("aria-busy", "true")
    expect(el).toHaveTextContent("Working…")
  })
})
