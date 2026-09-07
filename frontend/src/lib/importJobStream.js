import { API, getToken } from "@/lib/api"

export async function streamLeadImportJobEvents(jobId, onProgress) {
  const token = getToken()
  if (!token) {
    throw new Error("Missing access token for realtime updates")
  }

  const controller = new AbortController()
  const response = await fetch(
    `${API}/leads/import-jobs/${encodeURIComponent(jobId)}/events`,
    {
      method: "GET",
      headers: { Authorization: `Bearer ${token}` },
      signal: controller.signal,
      credentials: "include",
    },
  )
  if (!response.ok || !response.body) {
    throw new Error("Unable to connect to import progress stream")
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder("utf-8")
  let buffer = ""

  const processChunk = (chunk) => {
    buffer += chunk
    const parts = buffer.split("\n\n")
    buffer = parts.pop() ?? ""
    for (const part of parts) {
      const lines = part.split("\n")
      let eventName = "message"
      let dataLine = ""
      for (const line of lines) {
        if (line.startsWith("event:")) eventName = line.slice(6).trim()
        if (line.startsWith("data:")) dataLine += line.slice(5).trim()
      }
      if (eventName !== "progress" || !dataLine) continue
      try {
        const eventData = JSON.parse(dataLine)
        onProgress({
          id: eventData.jobId,
          status: eventData.status,
          failureReason: eventData.message,
          progress: {
            totalRows: eventData.totalRows || 0,
            processedRows: eventData.processedRows || 0,
            successRows: eventData.successRows || 0,
            failedRows: eventData.failedRows || 0,
            skippedRows: eventData.skippedRows || 0,
            created: eventData.created ?? eventData.successRows ?? 0,
            duplicates: eventData.duplicates || 0,
            invalid: eventData.invalid || 0,
          },
          errorCsvAvailable: false,
        })
      } catch {
        // Ignore malformed events.
      }
    }
  }

  void (async () => {
    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        processChunk(decoder.decode(value, { stream: true }))
      }
    } catch {
      // Caller handles fallback polling.
    }
  })()

  return () => controller.abort()
}
