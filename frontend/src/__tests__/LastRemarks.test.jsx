import { render, screen } from "@testing-library/react"
import { LastRemarks } from "@/components/leads/LastRemarks"

describe("LastRemarks", () => {
  it("renders truncated notes with title tooltip", () => {
    render(<LastRemarks notes="Customer asked for brochure" testId="lr" />)
    const el = screen.getByTestId("lr")
    expect(el).toHaveTextContent("Customer asked for brochure")
    expect(el.querySelector("[title]")).toHaveAttribute(
      "title",
      "Customer asked for brochure",
    )
  })

  it("renders empty dash when notes missing", () => {
    render(<LastRemarks notes={null} testId="lr-empty" />)
    expect(screen.getByTestId("lr-empty")).toHaveTextContent("—")
  })

  it("shows Last Remarks label when showLabel", () => {
    render(<LastRemarks notes="Prior note" showLabel testId="lr-label" />)
    expect(screen.getByTestId("lr-label")).toHaveTextContent("Last Remarks")
    expect(screen.getByTestId("lr-label")).toHaveTextContent("Prior note")
  })
})
