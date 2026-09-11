import { useCallback, useEffect, useState } from "react"
import api from "@/lib/api"

/**
 * Cloud calling UI stays off until LIVEKIT_* keys + live provider are configured.
 * Status.ui_enabled / enabled comes from GET /telephony/status.
 */
export function useTelephonyEnabled() {
  const [enabled, setEnabled] = useState(false)
  const [loading, setLoading] = useState(true)
  const [status, setStatus] = useState(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await api.get("/telephony/status")
      setStatus(data)
      setEnabled(Boolean(data?.ui_enabled ?? data?.enabled))
    } catch {
      setStatus(null)
      setEnabled(false)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  return { enabled, loading, status, refresh }
}
