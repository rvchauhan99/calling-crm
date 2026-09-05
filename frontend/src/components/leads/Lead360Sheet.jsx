import { useCallback, useEffect, useState } from "react"
import api, { formatApiError } from "@/lib/api"
import { useAuth } from "@/context/AuthContext"
import { StatusPill, Money } from "@/components/common"
import { Button } from "@/components/ui/button"
import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription,
} from "@/components/ui/sheet"
import { PipelineLogCallDialog } from "@/components/pipeline/PipelineLogCallDialog"
import { LastRemarks } from "@/components/leads/LastRemarks"
import { toast } from "sonner"
import { PhoneCall } from "lucide-react"

const formatMeta = (meta) => {
  if (!meta || typeof meta !== "object") return ""
  const parts = Object.entries(meta)
    .filter(([, v]) => v != null && v !== "")
    .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`)
  return parts.join(" · ")
}

export const Lead360Sheet = ({ leadId, onClose, onLogged }) => {
  const { can } = useAuth()
  const canLog = can("today_calls:log")
  const [detail, setDetail] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [dispositions, setDispositions] = useState([])
  const [logOpen, setLogOpen] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)

  const load = useCallback(async (id) => {
    if (!id) return
    setLoading(true)
    setError("")
    try {
      const { data } = await api.get(`/leads/${id}`)
      setDetail(data)
    } catch (e) {
      setDetail(null)
      setError(formatApiError(e.response?.data?.detail) || "Failed to load lead")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!leadId) {
      setDetail(null)
      setError("")
      setLogOpen(false)
      return
    }
    load(leadId)
  }, [leadId, load, refreshKey])

  useEffect(() => {
    if (!leadId || !canLog) return
    api.get("/dispositions").then((r) => {
      setDispositions((r.data.dispositions || []).filter((d) => d.active))
    }).catch(() => {})
  }, [leadId, canLog])

  const handleLogSubmit = async (payload) => {
    if (!detail?.lead) return
    if (!payload.disposition_id) {
      toast.error("Select a disposition")
      return
    }
    try {
      const { data: res } = await api.post("/calls/log", {
        lead_id: detail.lead.id,
        disposition_id: payload.disposition_id,
        outcome: "connected",
        notes: payload.notes || "",
        duration: payload.duration || 0,
        follow_up_at: payload.follow_up_at,
        pipeline_stage: payload.pipeline_stage,
        ...(payload.deposit_amount != null ? { deposit_amount: payload.deposit_amount } : {}),
      })
      if (res.converted) {
        toast.success(res.deposit_posted
          ? "Lead converted to client · Deposit posted"
          : "Lead converted to client")
      } else toast.success(res.acw ? "Logged — after-call work pending" : "Call logged")
      setLogOpen(false)
      setRefreshKey((k) => k + 1)
      onLogged?.(detail.lead.id, res)
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail))
    }
  }

  const lead = detail?.lead
  const calls = detail?.calls || []
  const activity = detail?.activity || []
  const client = detail?.client

  const fields = lead ? [
    ["Source", lead.source],
    ["City", lead.city || "—"],
    ["Stage", lead.pipeline_stage],
    ["Assigned", lead.assigned_name || "—"],
    ["Disposition", lead.disposition_name || "—"],
    ["Status", lead.status],
    ["Follow-up", lead.follow_up_at ? new Date(lead.follow_up_at).toLocaleString("en-IN") : "—"],
    ["Created", lead.created_at ? new Date(lead.created_at).toLocaleString("en-IN") : "—"],
    ["Updated", lead.updated_at ? new Date(lead.updated_at).toLocaleString("en-IN") : "—"],
  ] : []

  const customEntries = lead?.custom_fields && typeof lead.custom_fields === "object"
    ? Object.entries(lead.custom_fields).filter(([, v]) => v != null && v !== "")
    : []

  return (
    <>
      <Sheet open={!!leadId} onOpenChange={(o) => !o && onClose?.()}>
        <SheetContent className="w-full overflow-y-auto bg-white sm:max-w-2xl" data-testid="lead-360">
          {loading && !lead && (
            <p className="mt-8 text-sm text-slate-400" data-testid="lead-360-loading">Loading…</p>
          )}
          {error && (
            <p className="mt-8 text-sm text-red-600" data-testid="lead-360-error">{error}</p>
          )}
          {lead && (
            <>
              <SheetHeader>
                <SheetTitle className="font-display text-xl">{lead.name}</SheetTitle>
                <SheetDescription>
                  <span className="tabular">{lead.phone}</span>
                  {lead.email ? ` · ${lead.email}` : ""}
                </SheetDescription>
              </SheetHeader>

              <div className="mt-3 flex flex-wrap gap-1.5">
                {lead.pipeline_stage && <StatusPill color="sky">{lead.pipeline_stage}</StatusPill>}
                {lead.status && <StatusPill color="slate">{lead.status}</StatusPill>}
                {lead.disposition_name && (
                  <StatusPill color={lead.carry_forward ? "sky" : "amber"}>{lead.disposition_name}</StatusPill>
                )}
              </div>

              <LastRemarks
                notes={lead.last_notes}
                showLabel
                compact
                className="mt-3 rounded-md border border-slate-100 bg-slate-50 p-2.5"
                testId="lead-360-last-remarks"
              />

              {canLog && (
                <div className="mt-4">
                  <Button
                    className="w-full bg-sky-500 hover:bg-sky-600"
                    onClick={() => setLogOpen(true)}
                    data-testid="lead-360-log-call"
                  >
                    <PhoneCall size={15} className="mr-1.5" /> Log Call
                  </Button>
                </div>
              )}

              <div className="mt-5 grid grid-cols-2 gap-3 text-sm">
                {fields.map(([k, v]) => (
                  <div key={k} className="rounded-md bg-slate-50 p-2.5">
                    <p className="text-[11px] uppercase tracking-wide text-slate-400">{k}</p>
                    <p className="mt-0.5 font-medium text-slate-700">{v}</p>
                  </div>
                ))}
                {customEntries.map(([k, v]) => (
                  <div key={`cf-${k}`} className="rounded-md bg-slate-50 p-2.5">
                    <p className="text-[11px] uppercase tracking-wide text-slate-400">{k}</p>
                    <p className="mt-0.5 font-medium text-slate-700">{String(v)}</p>
                  </div>
                ))}
              </div>

              {client && (
                <div className="mt-4 rounded-md border border-sky-200 bg-sky-50 p-3 text-sm" data-testid="lead-360-client">
                  <p className="font-semibold text-sky-800">Converted to client</p>
                  <p className="text-sky-700">
                    {client.name} · Balance: <Money value={client.balance} />
                  </p>
                </div>
              )}

              <h4 className="mt-6 font-display text-sm font-semibold text-slate-800">
                Call history ({calls.length})
              </h4>
              <div className="mt-2 space-y-2" data-testid="lead-360-calls">
                {calls.length === 0 && <p className="text-sm text-slate-400">No calls logged.</p>}
                {calls.map((c) => (
                  <div key={c.id} className="rounded-md border border-slate-200 p-3 text-sm">
                    <div className="flex justify-between gap-2">
                      <StatusPill>{c.disposition_name}</StatusPill>
                      <span className="shrink-0 text-xs text-slate-400">
                        {new Date(c.created_at).toLocaleString("en-IN")}
                      </span>
                    </div>
                    {c.notes && <p className="mt-1.5 text-slate-600">{c.notes}</p>}
                    <p className="mt-1 text-xs text-slate-400">by {c.agent_name}</p>
                  </div>
                ))}
              </div>

              <h4 className="mt-6 font-display text-sm font-semibold text-slate-800">
                Actions ({activity.length})
              </h4>
              <div className="mt-2 space-y-2" data-testid="lead-360-activity">
                {activity.length === 0 && <p className="text-sm text-slate-400">No actions recorded.</p>}
                {activity.map((a) => (
                  <div key={a.id} className="rounded-md border border-slate-200 p-3 text-sm">
                    <div className="flex justify-between gap-2">
                      <p className="font-medium text-slate-800">
                        {a.action}
                        {a.entity ? <span className="font-normal text-slate-500"> · {a.entity}</span> : null}
                      </p>
                      <span className="shrink-0 text-xs text-slate-400">
                        {a.created_at ? new Date(a.created_at).toLocaleString("en-IN") : ""}
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-slate-400">by {a.actor_name || "system"}</p>
                    {formatMeta(a.meta) && (
                      <p className="mt-1 text-xs text-slate-500">{formatMeta(a.meta)}</p>
                    )}
                  </div>
                ))}
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>

      <PipelineLogCallDialog
        open={logOpen}
        lead={lead}
        dispositions={dispositions}
        mode="log"
        onClose={() => setLogOpen(false)}
        onSubmit={handleLogSubmit}
      />
    </>
  )
}
