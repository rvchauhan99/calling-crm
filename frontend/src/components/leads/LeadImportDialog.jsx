import { useEffect, useRef, useState } from "react"
import api, { API, getToken, formatApiError } from "@/lib/api"
import { streamLeadImportJobEvents } from "@/lib/importJobStream"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Progress } from "@/components/ui/progress"
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog"
import { toast } from "sonner"
import { Download, Upload } from "lucide-react"

const emptyProgress = {
  totalRows: 0,
  processedRows: 0,
  successRows: 0,
  failedRows: 0,
  skippedRows: 0,
  created: 0,
  duplicates: 0,
  invalid: 0,
}

function triggerCsvDownload(blob, fileName) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = fileName
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

function parseDispositionFileName(header) {
  const match = /filename\*?=(?:UTF-8''|")?([^\";]+)/i.exec(header || "")
  if (!match) return null
  try {
    return decodeURIComponent(match[1].replace(/"/g, ""))
  } catch {
    return match[1].replace(/"/g, "")
  }
}

export function LeadImportDialog({ open, onOpenChange, onComplete }) {
  const fileInputRef = useRef(null)
  const streamCleanupRef = useRef(null)
  const pollTimerRef = useRef(null)
  const downloadedErrorCsvJobsRef = useRef(new Set())

  const [file, setFile] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [importJob, setImportJob] = useState(null)
  const submittingRef = useRef(false)

  const status = importJob?.status
  const isBusy = submitting || status === "queued" || status === "processing"

  const stopTracking = () => {
    if (streamCleanupRef.current) {
      streamCleanupRef.current()
      streamCleanupRef.current = null
    }
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current)
      pollTimerRef.current = null
    }
  }

  useEffect(() => {
    return () => stopTracking()
  }, [])

  useEffect(() => {
    if (open) return
    stopTracking()
    setFile(null)
    setSubmitting(false)
    setImportJob(null)
    if (fileInputRef.current) fileInputRef.current.value = ""
  }, [open])

  const handleOpenChange = (next) => {
    if (!next && isBusy) return
    onOpenChange(next)
  }

  const downloadTemplate = async () => {
    try {
      const res = await fetch(`${API}/leads/import/template`, {
        headers: { Authorization: `Bearer ${getToken()}` },
      })
      if (!res.ok) throw new Error("Failed to download template")
      const blob = await res.blob()
      triggerCsvDownload(blob, "leads_import_template.csv")
    } catch (err) {
      toast.error(err.message)
    }
  }

  const downloadErrorCsv = async (jobId) => {
    const res = await api.get(`/leads/import-jobs/${encodeURIComponent(jobId)}/errors.csv`, {
      responseType: "blob",
    })
    const fileName = parseDispositionFileName(res.headers["content-disposition"])
      || `lead-import-errors-${jobId}.csv`
    triggerCsvDownload(res.data, fileName)
  }

  const handleDownloadErrorCsv = async () => {
    if (!importJob?.id) return
    try {
      await downloadErrorCsv(importJob.id)
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Failed to download error CSV")
    }
  }

  const maybeAutoDownloadErrors = async (job) => {
    if (!job?.errorCsvAvailable || !job.id) return
    if (downloadedErrorCsvJobsRef.current.has(job.id)) return
    downloadedErrorCsvJobsRef.current.add(job.id)
    try {
      await downloadErrorCsv(job.id)
      toast.error("Some rows could not be imported.", {
        description: "Error records were downloaded as a CSV with original columns.",
      })
    } catch {
      // Keep the on-screen download button as fallback.
    }
  }

  const startTracking = async (jobId) => {
    stopTracking()
    const refreshStatus = async () => {
      try {
        const { data } = await api.get(`/leads/import-jobs/${encodeURIComponent(jobId)}`)
        setImportJob(data)
        if (data.status === "completed") {
          stopTracking()
          const created = data.progress?.created ?? data.progress?.successRows ?? 0
          const duplicates = data.progress?.duplicates ?? 0
          const invalid = data.progress?.invalid ?? 0
          toast.success(`Imported ${created} · ${duplicates} dupes · ${invalid} invalid`)
          await maybeAutoDownloadErrors(data)
          onComplete?.()
        } else if (data.status === "failed") {
          stopTracking()
          toast.error(data.failureReason || "Import failed.")
          await maybeAutoDownloadErrors(data)
        }
      } catch {
        // Keep polling retries silent.
      }
    }

    try {
      const cleanup = await streamLeadImportJobEvents(jobId, (streamed) => {
        setImportJob((prev) => ({
          ...(prev || { id: jobId, fileName: "", errorSample: [] }),
          id: streamed.id || jobId,
          status: streamed.status,
          failureReason: streamed.failureReason,
          progress: {
            ...emptyProgress,
            ...(prev?.progress || {}),
            ...(streamed.progress || {}),
          },
          errorCsvAvailable: prev?.errorCsvAvailable || false,
        }))
      })
      streamCleanupRef.current = cleanup
    } catch {
      // Polling covers a dropped stream.
    }

    pollTimerRef.current = setInterval(() => {
      void refreshStatus()
    }, 7000)
    void refreshStatus()
  }

  const handleImport = async () => {
    if (!file) {
      toast.error("Choose a CSV file.")
      return
    }
    if (submittingRef.current) return
    submittingRef.current = true
    setSubmitting(true)
    try {
      const fd = new FormData()
      fd.append("file", file)
      const { data } = await api.post("/leads/import-jobs", fd)
      setFile(null)
      if (fileInputRef.current) fileInputRef.current.value = ""
      toast.success("Import accepted. Processing started in background.")
      setImportJob({
        id: data.jobId,
        status: data.status || "queued",
        progress: { ...emptyProgress },
        errorCsvAvailable: false,
      })
      await startTracking(data.jobId)
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Import failed")
    } finally {
      submittingRef.current = false
      setSubmitting(false)
    }
  }

  const progress = importJob?.progress || emptyProgress
  const total = progress.totalRows || 0
  const processed = progress.processedRows || 0
  const percent = total > 0 ? Math.round((processed / total) * 100) : (status === "completed" ? 100 : 0)

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent
        data-testid="lead-import-dialog"
        className="sm:max-w-lg"
        onPointerDownOutside={(e) => { if (isBusy) e.preventDefault() }}
        onEscapeKeyDown={(e) => { if (isBusy) e.preventDefault() }}
      >
        <DialogHeader>
          <DialogTitle>Import leads</DialogTitle>
          <DialogDescription>
            Upload a CSV. Valid rows are imported immediately in the background. Failed rows can be downloaded with all original columns.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div>
            <Label htmlFor="lead-import-file">Lead file (CSV)</Label>
            <input
              id="lead-import-file"
              ref={fileInputRef}
              type="file"
              accept=".csv"
              className="mt-1.5 block w-full text-sm text-slate-600 file:mr-3 file:rounded-md file:border file:border-slate-200 file:bg-white file:px-3 file:py-1.5"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              disabled={isBusy}
              data-testid="lead-import-file"
            />
            <Button
              type="button"
              variant="link"
              size="sm"
              onClick={downloadTemplate}
              className="mt-1 h-auto px-0"
              data-testid="lead-import-template-btn"
            >
              Download template
            </Button>
          </div>

          {importJob ? (
            <div className="space-y-2 rounded-md border border-slate-200 p-3 text-sm" data-testid="lead-import-progress">
              <div className="font-medium capitalize" data-testid="lead-import-status">
                Import status: {importJob.status}
              </div>
              <Progress value={percent} aria-label="Import progress" />
              <div className="text-slate-500" data-testid="lead-import-counts">
                Processed {processed}/{total} rows
              </div>
              <div className="text-slate-500">
                Created: {progress.created ?? progress.successRows ?? 0} · Dupes: {progress.duplicates ?? 0} · Invalid: {progress.invalid ?? 0} · Skipped: {progress.skippedRows ?? 0}
              </div>
              {importJob.failureReason ? (
                <div className="text-red-600">{importJob.failureReason}</div>
              ) : null}
              {importJob.errorCsvAvailable ? (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={handleDownloadErrorCsv}
                  data-testid="lead-import-error-csv-btn"
                >
                  <Download size={16} className="mr-1.5" /> Download error CSV
                </Button>
              ) : null}
            </div>
          ) : null}
        </div>

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => handleOpenChange(false)}
            disabled={isBusy}
          >
            Close
          </Button>
          <Button
            type="button"
            onClick={handleImport}
            disabled={isBusy || !file}
            data-testid="lead-import-submit-btn"
          >
            <Upload size={16} className="mr-1.5" />
            {isBusy ? "Importing…" : "Import"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
