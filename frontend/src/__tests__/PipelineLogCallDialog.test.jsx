import { render, screen, waitFor, fireEvent } from "@testing-library/react"
import { PipelineLogCallDialog } from "@/components/pipeline/PipelineLogCallDialog"

jest.mock("@/components/ui/searchable-select", () => ({
  SearchableSelect: ({ label, value, onChange, options, testId }) => (
    <div data-testid={testId}>
      {label && <span>{label}</span>}
      <select
        aria-label={label || testId}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        data-testid={`${testId}-select`}
      >
        <option value="">Select</option>
        {(options || []).map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
  ),
}))

const lead = { id: "l1", name: "Lead A", phone: "+919999999999", pipeline_stage: "New" }

const dispositions = [
  { id: "d-int", name: "Interested", color: "#0EA5E9", converts_to_client: false, default_pipeline_stage: "Qualified" },
  { id: "d-conv", name: "Converted", color: "#0369A1", converts_to_client: true, default_pipeline_stage: "Won", requires_acw: true },
]

describe("PipelineLogCallDialog deposit", () => {
  it("hides deposit for non-convert disposition", async () => {
    render(
      <PipelineLogCallDialog
        open
        lead={lead}
        dispositions={dispositions}
        mode="log"
        onClose={() => {}}
        onSubmit={() => {}}
      />,
    )
    fireEvent.change(screen.getByTestId("pipeline-disposition-select-select"), {
      target: { value: "d-int" },
    })
    expect(screen.queryByTestId("convert-deposit-amount")).not.toBeInTheDocument()
  })

  it("shows deposit for convert disposition and includes amount in submit", async () => {
    const onSubmit = jest.fn()
    render(
      <PipelineLogCallDialog
        open
        lead={lead}
        dispositions={dispositions}
        mode="log"
        onClose={() => {}}
        onSubmit={onSubmit}
      />,
    )
    fireEvent.change(screen.getByTestId("pipeline-disposition-select-select"), {
      target: { value: "d-conv" },
    })
    await waitFor(() => {
      expect(screen.getByTestId("convert-deposit-amount")).toBeInTheDocument()
    })
    fireEvent.change(screen.getByTestId("convert-deposit-amount"), {
      target: { value: "1500" },
    })
    fireEvent.click(screen.getByTestId("pipeline-log-submit"))
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        disposition_id: "d-conv",
        deposit_amount: 1500,
        pipeline_stage: "Won",
      }),
    )
  })
})
