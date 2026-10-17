import { useCallback, useEffect, useRef, useState } from "react"
import api, { formatApiError } from "@/lib/api"
import { loadStringeeSdk } from "@/lib/stringeeSdk"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { Phone, PhoneOff, Mic, MicOff, Loader2 } from "lucide-react"
import { toast } from "sonner"

/**
 * Softphone dock — mock simulates connect; Stringee PCC click-to-call (answer in StringeeX);
 * web_sdk mode uses Stringee Web SDK; other providers use originate API.
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
  const [crmCallId, setCrmCallId] = useState(null)
  const [pendingCallId, setPendingCallId] = useState(null)
  const [elapsed, setElapsed] = useState(0)
  const [busy, setBusy] = useState(false)
  const [selectedFrom, setSelectedFrom] = useState("")
  const clientRef = useRef(null)
  const callRef = useRef(null)
  const remoteAudioRef = useRef(null)
  const reconcileTimerRef = useRef(null)

  useEffect(() => {
    if (status !== "in_call" && status !== "ringing") return undefined
    const t = setInterval(() => setElapsed((s) => s + 1), 1000)
    return () => clearInterval(t)
  }, [status])

  const stopReconcile = useCallback(() => {
    if (reconcileTimerRef.current) {
      clearInterval(reconcileTimerRef.current)
      reconcileTimerRef.current = null
    }
  }, [])

  const teardownStringee = useCallback(() => {
    stopReconcile()
    try {
      if (callRef.current) {
        try { callRef.current.hangup?.(() => {}) } catch { /* ignore */ }
        callRef.current = null
      }
      if (clientRef.current) {
        try { clientRef.current.disconnect?.() } catch { /* ignore */ }
        clientRef.current = null
      }
    } catch { /* ignore */ }
  }, [stopReconcile])

  const reset = useCallback(() => {
    teardownStringee()
    setStatus("idle")
    setSession(null)
    setMuted(false)
    setProviderCallId(null)
    setCrmCallId(null)
    setPendingCallId(null)
    setElapsed(0)
    setBusy(false)
    setSelectedFrom("")
  }, [teardownStringee])

  useEffect(() => {
    if (!open) reset()
  }, [open, reset])

  // Prefetch session when dock opens so CLI picker is ready before dial
  useEffect(() => {
    if (!open || status !== "idle") return undefined
    let cancelled = false
    api.post("/telephony/softphone/session", { lead_id: leadId || null })
      .then(({ data: sess }) => {
        if (cancelled || !sess) return
        setSession(sess)
        const list = sess.from_numbers || []
        if (list.length) {
          setSelectedFrom(
            sess.from_number
              || list.find((n) => n.is_default)?.e164
              || list[0].e164,
          )
        }
      })
      .catch(() => {})
    return () => { cancelled = true }
  }, [open, leadId, status])

  const startPccReconcile = (callId) => {
    stopReconcile()
    if (!callId) return
    let ticks = 0
    reconcileTimerRef.current = setInterval(async () => {
      ticks += 1
      try {
        const { data } = await api.post("/telephony/stringee/reconcile", { call_id: callId })
        if (data?.provider_call_id) setProviderCallId(data.provider_call_id)
        if (data?.reconciled && data?.status && data.status !== "ringing") {
          if (data.status === "answered" || (data.talk_sec || 0) > 0) {
            setStatus("in_call")
          }
          if (["completed", "missed", "failed"].includes(data.status)) {
            stopReconcile()
          }
        }
      } catch { /* ignore poll errors */ }
      if (ticks >= 60) stopReconcile()
    }, 4000)
  }

  const dialStringeeSdk = async (sess, fromNumber) => {
    const { StringeeClient, StringeeCall } = await loadStringeeSdk()
    const client = new StringeeClient()
    clientRef.current = client

    await new Promise((resolve, reject) => {
      const t = setTimeout(() => reject(new Error("Stringee connect timeout")), 20000)
      client.on("connect", () => {})
      client.on("authen", (res) => {
        clearTimeout(t)
        if (res?.r === 0 || res?.message === "SUCCESS" || res?.userId) {
          resolve(res)
        } else {
          reject(new Error(res?.message || "Stringee auth failed"))
        }
      })
      client.on("disconnect", () => {})
      client.connect(sess.token)
    })

    const custom = JSON.stringify({
      lead_id: leadId || null,
      room_name: sess.room_name || "",
    })

    const call = new StringeeCall(client, fromNumber || sess.from_number || sess.identity, leadPhone, false)
    callRef.current = call
    try {
      call.customData = custom
    } catch { /* ignore */ }

    call.on("addremotestream", (stream) => {
      const el = remoteAudioRef.current
      if (el) {
        el.srcObject = stream
        el.play?.().catch(() => {})
      }
    })
    call.on("signalingstate", (state) => {
      const code = state?.code ?? state
      if (code === 2 || state?.reason === "Ringing") setStatus("ringing")
      if (code === 3 || code === 4 || state?.reason === "Answered" || state?.reason === "Connected") {
        setStatus("in_call")
      }
    })

    const { data: crmCall } = await api.post("/telephony/originate", {
      to_number: leadPhone,
      lead_id: leadId || null,
      room_name: sess.room_name,
      from_number: fromNumber || sess.from_number || undefined,
    })
    setPendingCallId(crmCall.provider_call_id)
    setCrmCallId(crmCall.call_id || null)

    await new Promise((resolve, reject) => {
      call.makeCall((res) => {
        if (res?.r === 0 || res?.callId || call.callId) {
          const realId = res?.callId || call.callId
          if (realId) {
            setProviderCallId(realId)
            api.post("/telephony/stringee/bind-call", {
              pending_provider_call_id: crmCall.provider_call_id,
              provider_call_id: realId,
              lead_id: leadId || null,
            }).catch(() => {})
          } else {
            setProviderCallId(crmCall.provider_call_id)
          }
          resolve(res)
        } else {
          reject(new Error(res?.message || `Make call failed (r=${res?.r})`))
        }
      })
    })

    setStatus("ringing")
    setElapsed(0)
    toast.success("Calling…")
  }

  const dialPcc = async (sess, fromNumber) => {
    const { data: call } = await api.post("/telephony/originate", {
      to_number: leadPhone,
      lead_id: leadId || null,
      room_name: sess.room_name,
      from_number: fromNumber || sess.from_number || undefined,
    })
    setProviderCallId(call.provider_call_id)
    setCrmCallId(call.call_id || null)
    setStatus("ringing")
    setElapsed(0)
    toast.success("Calling — answer in StringeeX")
    if (call.call_id) startPccReconcile(call.call_id)
  }

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
      const fromList = sess.from_numbers || []
      const cli = selectedFrom || sess.from_number || (fromList.find((n) => n.is_default)?.e164) || fromList[0]?.e164 || ""
      if (!selectedFrom && cli) setSelectedFrom(cli)
      setStatus("ringing")

      if (sess.provider === "stringee" && !sess.mock) {
        if (sess.dial_mode === "web_sdk" && sess.token) {
          await dialStringeeSdk(sess, cli)
          return
        }
        await dialPcc(sess, cli)
        return
      }

      const { data: call } = await api.post("/telephony/originate", {
        to_number: leadPhone,
        lead_id: leadId || null,
        room_name: sess.room_name,
        from_number: cli || undefined,
      })
      setProviderCallId(call.provider_call_id)
      setCrmCallId(call.call_id || null)
      setStatus("in_call")
      setElapsed(0)
      if (call.mock) {
        toast.message("Mock call connected (TELEPHONY_PROVIDER=mock)")
      } else {
        toast.success("Calling…")
      }
    } catch (e) {
      teardownStringee()
      setStatus("idle")
      toast.error(formatApiError(e.response?.data?.detail) || e.message || "Dial failed")
    } finally {
      setBusy(false)
    }
  }

  const handleHangup = async () => {
    setBusy(true)
    try {
      const callId = providerCallId || pendingCallId
      if (session?.provider === "stringee" && callRef.current) {
        try {
          await new Promise((resolve) => {
            try {
              callRef.current.hangup(() => resolve())
            } catch {
              resolve()
            }
            setTimeout(resolve, 1500)
          })
        } catch { /* ignore */ }
      }
      if (crmCallId && session?.dial_mode === "pcc") {
        await api.post("/telephony/stringee/reconcile", { call_id: crmCallId }).catch(() => {})
      }
      if (callId) {
        await api.post("/telephony/hangup", { provider_call_id: callId }).catch(() => {})
        if (session?.mock) {
          await api.post("/telephony/webhooks/mock", {
            event: "completed",
            provider_call_id: callId,
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
      const endedId = callId
      reset()
      onClose?.()
      onEnded?.({
        leadId,
        duration,
        providerCallId: endedId,
        mock: Boolean(session?.mock),
      })
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail) || "Hangup failed")
    } finally {
      setBusy(false)
    }
  }

  const toggleMute = () => {
    setMuted((m) => {
      const next = !m
      try {
        callRef.current?.mute?.(next)
      } catch { /* ignore */ }
      return next
    })
  }

  if (!open) return null

  const mm = String(Math.floor(elapsed / 60)).padStart(2, "0")
  const ss = String(elapsed % 60).padStart(2, "0")
  const fromNumbers = session?.from_numbers || []
  const showCliPicker = status === "idle" || (session && fromNumbers.length > 1)

  return (
    <div
      className="fixed bottom-4 right-4 z-50 w-80 rounded-xl border border-slate-200 bg-white p-4 shadow-xl"
      data-testid="softphone-dock"
      role="dialog"
      aria-label="Softphone"
    >
      <audio ref={remoteAudioRef} autoPlay playsInline className="hidden" data-testid="softphone-remote-audio" />
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
      {session?.provider === "stringee" && !session?.mock && (
        <p className="mt-2 text-[11px] text-emerald-700" data-testid="softphone-stringee-badge">
          Stringee · {session.stringee_user_id || session.identity}
          {session.dial_mode === "pcc" ? " · Answer in StringeeX" : ""}
        </p>
      )}

      {status === "idle" && fromNumbers.length > 1 && (
        <label className="mt-2 block text-[11px] text-slate-500">
          Caller ID
          <select
            className="mt-1 w-full rounded-md border border-slate-200 bg-white px-2 py-1.5 text-xs text-slate-800"
            value={selectedFrom || fromNumbers.find((n) => n.is_default)?.e164 || fromNumbers[0]?.e164 || ""}
            onChange={(e) => setSelectedFrom(e.target.value)}
            data-testid="softphone-cli-select"
          >
            {fromNumbers.map((n) => (
              <option key={n.e164} value={n.e164}>
                {n.label || n.e164}{n.is_default ? " (default)" : ""}
              </option>
            ))}
          </select>
        </label>
      )}
      {showCliPicker && session && fromNumbers.length > 1 && status !== "idle" && (
        <p className="mt-1 text-[10px] text-slate-400" data-testid="softphone-cli-active">
          CLI {selectedFrom || session.from_number}
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
              onClick={toggleMute}
              data-testid="softphone-mute"
              aria-label={muted ? "Unmute" : "Mute"}
              disabled={session?.dial_mode === "pcc"}
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
