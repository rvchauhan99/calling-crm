import { useCallback, useEffect, useState } from "react"
import api, { formatApiError } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { Phone, PhoneOff, Mic, MicOff, Loader2 } from "lucide-react"
import { toast } from "sonner"

/**
 * Softphone dock — mock mode simulates connect; LiveKit mode uses token session.
 * Hangup triggers onEnded so parent can open disposition dialog.
 */
export function SoftphoneDock({
  leadId,
  leadPhone,
  leadName,
  open,
  onClose,
  onEnded,
  canDial = true,
}) {
  const [status, setStatus] = useState("idle")
  const [session, setSession] = useState(null)
  const [muted, setMuted] = useState(false)
  const [providerCallId, setProviderCallId] = useState(null)
  const [elapsed, setElapsed] = useState(0)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (status !== "in_call" && status !== "ringing") return undefined
    const t = setInterval(() => setElapsed((s) => s + 1), 1000)
    return () => clearInterval(t)
  }, [status])

  const reset = useCallback(() => {
    setStatus("idle")
    setSession(null)
    setMuted(false)
    setProviderCallId(null)
    setElapsed(0)
    setBusy(false)
  }, [])

  useEffect(() => {
    if (!open) reset()
  }, [open, reset])

  const handleDial = async () => {
    if (!canDial || !leadPhone) {
      toast.error("No phone number")
      return
    }
    setBusy(true)
    try {
      const { data: sess } = await api.post("/telephony/softphone/session", {
        lead_id: leadId || null,
      })
      setSession(sess)
      setStatus("ringing")
      const { data: call } = await api.post("/telephony/originate", {
        to_number: leadPhone,
        lead_id: leadId || null,
        room_name: sess.room_name,
      })
      setProviderCallId(call.provider_call_id)
      setStatus("in_call")
      setElapsed(0)
      if (call.mock) {
        toast.message("Mock call connected (TELEPHONY_PROVIDER=mock)")
      } else {
        toast.success("Calling…")
      }
    } catch (e) {
      setStatus("idle")
      toast.error(formatApiError(e.response?.data?.detail) || "Dial failed")
    } finally {
      setBusy(false)
    }
  }

  const handleHangup = async () => {
    setBusy(true)
    try {
      if (providerCallId) {
        await api.post("/telephony/hangup", { provider_call_id: providerCallId })
        // Simulate completed webhook for mock so CDR has talk_sec
        if (session?.mock) {
          await api.post("/telephony/webhooks/mock", {
            event: "completed",
            provider_call_id: providerCallId,
            status: "completed",
            direction: "outbound",
            to_number: leadPhone,
            talk_sec: elapsed,
            lead_id: leadId,
            room_name: session?.room_name,
          })
        }
      }
      const duration = elapsed
      reset()
      onClose?.()
      onEnded?.({
        leadId,
        duration,
        providerCallId,
        mock: Boolean(session?.mock),
      })
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail) || "Hangup failed")
    } finally {
      setBusy(false)
    }
  }

  if (!open) return null

  const mm = String(Math.floor(elapsed / 60)).padStart(2, "0")
  const ss = String(elapsed % 60).padStart(2, "0")

  return (
    <div
      className="fixed bottom-4 right-4 z-50 w-80 rounded-xl border border-slate-200 bg-white p-4 shadow-xl"
      data-testid="softphone-dock"
      role="dialog"
      aria-label="Softphone"
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-slate-400">Softphone</p>
          <p className="mt-0.5 text-sm font-semibold text-slate-900" data-testid="softphone-lead-name">
            {leadName || "Outbound"}
          </p>
          <p className="text-xs text-slate-500" data-testid="softphone-lead-phone">{leadPhone}</p>
        </div>
        <span
          className={cn(
            "rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase",
            status === "in_call" && "bg-emerald-100 text-emerald-700",
            status === "ringing" && "bg-amber-100 text-amber-700",
            status === "idle" && "bg-slate-100 text-slate-600",
          )}
          data-testid="softphone-status"
        >
          {status === "in_call" ? `${mm}:${ss}` : status}
        </span>
      </div>

      {session?.mock && (
        <p className="mt-2 text-[11px] text-sky-700" data-testid="softphone-mock-badge">
          Mock provider — no PSTN minutes used
        </p>
      )}

      <div className="mt-4 flex items-center justify-center gap-3">
        {status === "idle" ? (
          <Button
            type="button"
            className="h-12 w-12 rounded-full bg-emerald-600 hover:bg-emerald-700"
            onClick={handleDial}
            disabled={busy || !canDial}
            data-testid="softphone-dial"
            aria-label="Dial"
          >
            {busy ? <Loader2 className="h-5 w-5 animate-spin" /> : <Phone className="h-5 w-5" />}
          </Button>
        ) : (
          <>
            <Button
              type="button"
              variant="outline"
              className="h-10 w-10 rounded-full"
              onClick={() => setMuted((m) => !m)}
              data-testid="softphone-mute"
              aria-label={muted ? "Unmute" : "Mute"}
            >
              {muted ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
            </Button>
            <Button
              type="button"
              className="h-12 w-12 rounded-full bg-red-600 hover:bg-red-700"
              onClick={handleHangup}
              disabled={busy}
              data-testid="softphone-hangup"
              aria-label="Hang up"
            >
              {busy ? <Loader2 className="h-5 w-5 animate-spin" /> : <PhoneOff className="h-5 w-5" />}
            </Button>
          </>
        )}
      </div>

      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="mt-3 w-full text-xs text-slate-500"
        onClick={() => {
          if (status === "idle") {
            onClose?.()
            return
          }
          handleHangup()
        }}
        data-testid="softphone-close"
      >
        {status === "idle" ? "Close" : "End & log disposition"}
      </Button>
    </div>
  )
}
