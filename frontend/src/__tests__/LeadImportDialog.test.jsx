import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import api from "@/lib/api"
import { LeadImportDialog } from "@/components/leads/LeadImportDialog"
import { streamLeadImportJobEvents } from "@/lib/importJobStream"

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

jest.mock("@/lib/importJobStream", () => ({
  streamLeadImportJobEvents: jest.fn(),
}))

jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}))

const completedJob = {
  id: "job-1",
  status: "completed",
  failureReason: null,
  progress: {
    totalRows: 3,
    processedRows: 3,
    successRows: 1,
    failedRows: 2,
    skippedRows: 0,
    created: 1,
    duplicates: 1,
    invalid: 1,
  },
  errorSample: [],
  errorCsvAvailable: true,
}

describe("LeadImportDialog", () => {
  beforeEach(() => {
    jest.clearAllMocks()
    global.URL.createObjectURL = jest.fn(() => "blob:test")
    global.URL.revokeObjectURL = jest.fn()
    api.post.mockResolvedValue({ data: { jobId: "job-1", status: "queued" } })
    api.get.mockImplementation((url) => {
      if (String(url).includes("/errors.csv")) {
        return Promise.resolve({
          data: new Blob(["name,error_reason\n"]),
          headers: { "content-disposition": 'attachment; filename="lead-import-errors-job-1.csv"' },
        })
      }
      return Promise.resolve({ data: completedJob })
    })
    streamLeadImportJobEvents.mockImplementation(async (_jobId, onProgress) => {
      onProgress({
        id: "job-1",
        status: "processing",
        progress: {
          totalRows: 3,
          processedRows: 1,
          successRows: 1,
          failedRows: 0,
          skippedRows: 0,
          created: 1,
          duplicates: 0,
          invalid: 0,
        },
        errorCsvAvailable: false,
      })
      return () => {}
    })
  })

  it("shows live progress and error CSV download after a successful import", async () => {
    const onComplete = jest.fn()
    render(<LeadImportDialog open onOpenChange={jest.fn()} onComplete={onComplete} />)

    expect(screen.getByTestId("lead-import-dialog")).toBeInTheDocument()

    const file = new File(["name,phone\nA,9876543210\n"], "leads.csv", { type: "text/csv" })
    await userEvent.upload(screen.getByTestId("lead-import-file"), file)
    await userEvent.click(screen.getByTestId("lead-import-submit-btn"))

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/leads/import-jobs", expect.any(FormData))
    })
    await waitFor(() => {
      expect(screen.getByTestId("lead-import-progress")).toBeInTheDocument()
    })
    await waitFor(() => {
      expect(screen.getByTestId("lead-import-counts")).toHaveTextContent("Processed 3/3 rows")
    })
    expect(screen.getByTestId("lead-import-status")).toHaveTextContent("completed")
    expect(screen.getByTestId("lead-import-error-csv-btn")).toBeInTheDocument()
    expect(onComplete).toHaveBeenCalled()

    await userEvent.click(screen.getByTestId("lead-import-error-csv-btn"))
    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith("/leads/import-jobs/job-1/errors.csv", { responseType: "blob" })
    })
  })

  it("does not submit without a file", async () => {
    render(<LeadImportDialog open onOpenChange={jest.fn()} />)
    expect(screen.getByTestId("lead-import-submit-btn")).toBeDisabled()
    expect(api.post).not.toHaveBeenCalled()
  })
})
