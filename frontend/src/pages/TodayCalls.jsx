import { useEffect, useState, useCallback, useMemo, useRef } from "react"
import api, { formatApiError } from "@/lib/api"
import { EmptyState, PageLoader, StatusPill } from "@/components/common"
import { LeadPhoneLink } from "@/components/leads/LeadPhoneLink"
import { Lead360Sheet } from "@/components/leads/Lead360Sheet"
import { LastRemarks } from "@/components/leads/LastRemarks"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"
import { Input } from "@/components/ui/input"
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog"
import { SearchableSelect } from "@/components/ui/searchable-select"
import { toast } from "sonner"
import {
  PhoneCall, PhoneOutgoing, AlertTriangle, CheckCircle2, Search,
} from "lucide-react"
import { cn } from "@/lib/utils"
import {
  QUEUE_BUCKETS,
  urgencyLabel,
  nowDatetimeLocalValue,
  isCallBackDisposition,
  isConvertDisposition,
  isTerminalStage,
  parseDepositAmount,
} from "@/lib/followupBuckets"
import { mappedStageForDisposition, PIPELINE_STAGES as STAGES } from "@/components/pipeline/PipelineLogCallDialog"
const SORTS = [
  { id: "urgency", label: "Urgency" },
  { id: "soonest", label: "Soonest FU" },
  { id: "name", label: "Name" },
]

const bucketPill = (reason) => {
  if (reason === "overdue") return "red"
  if (reason === "due_today") return "amber"
  if (reason === "assigned_today") return "sky"
  if (reason === "called_today") return "emerald"
  return "slate"
}

const DISPLAY_SECTIONS = [
  ...QUEUE_BUCKETS,
  { id: "called_today", label: "Called today", color: "emerald" },
]

export default function TodayCalls() {
  const [data, setData] = useState(null)
  const [dispositions, setDispositions] = useState([])
  const [active, setActive] = useState(null)
  const [lead360Id, setLead360Id] = useState(null)
  const [form, setForm] = useState({
    disposition_id: "", notes: "", follow_up_at: "", pipeline_stage: "", duration: 0, deposit_amount: "",
  })
  const [bucketFilter, setBucketFilter] = useState("all")
  const [search, setSearch] = useState("")
  const [stageFilter, setStageFilter] = useState("")
  const [sourceFilter, setSourceFilter] = useState("")
  const [dispositionFilter, setDispositionFilter] = useState("")
  const [sortBy, setSortBy] = useState("urgency")
  const [highlightAcw, setHighlightAcw] = useState(false)
  const acwFocusPending = useRef(false)

  const load = useCallback(async () => {
    const [tc, ds] = await Promise.all([api.get("/today-calls"), api.get("/dispositions")])
    setData(tc.data)
    setDispositions((ds.data.dispositions || []).filter((d) => d.active))
  }, [])

  useEffect(() => { load().catch(() => {}) }, [load])

  const openLog = (lead) => {
    setActive(lead)
    setForm({
      disposition_id: "",
      notes: "",
      follow_up_at: "",
      pipeline_stage: lead.pipeline_stage || "New",
      duration: 0,
      deposit_amount: "",
    })
  }

  const submit = async () => {
    if (!form.disposition_id) { toast.error("Select a disposition"); return }
    const disp = dispositions.find((d) => d.id === form.disposition_id)
    if (isCallBackDisposition(disp) && !form.follow_up_at) {
      toast.error("Follow-up required for Call Back")
      return
    }
    try {
      const converts = isConvertDisposition(disp)
      const terminal = isTerminalStage(form.pipeline_stage) || converts
      const deposit = converts ? parseDepositAmount(form.deposit_amount) : null
      const payload = {
        lead_id: active.id,
        disposition_id: form.disposition_id,
        notes: form.notes,
        duration: Number(form.duration) || 0,
        pipeline_stage: form.pipeline_stage,
        follow_up_at: terminal || !form.follow_up_at
          ? null
          : new Date(form.follow_up_at).toISOString(),
      }
      if (deposit != null) payload.deposit_amount = deposit
      const { data: res } = await api.post("/calls/log", payload)
      if (res.converted) {
        toast.success(res.deposit_posted
          ? "Lead converted to client · Deposit posted"
          : "Lead converted to client")
      } else toast.success(res.acw ? "Logged — after-call work pending" : "Call logged")
      setActive(null)
      load()
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail))
    }
  }

  const completeAcw = async () => {
    await api.post("/calls/complete-acw")
    toast.success("After-call work completed")
    load()
  }

  const sources = useMemo(() => {
    if (!data?.buckets) return []
    const set = new Set()
    Object.values(data.buckets).flat().forEach((l) => {
      if (l.source) set.add(l.source)
    })
    return [...set].sort()
  }, [data])

  const dispositionNames = useMemo(() => {
    if (!data?.buckets) return []
    const set = new Set()
    Object.values(data.buckets).flat().forEach((l) => {
      if (l.disposition_name) set.add(l.disposition_name)
    })
    return [...set].sort()
  }, [data])

  const filterLead = useCallback((lead) => {
    if (search) {
      const q = search.toLowerCase()
      const hay = `${lead.name || ""} ${lead.phone || ""}`.toLowerCase()
      if (!hay.includes(q)) return false
    }
    if (stageFilter && lead.pipeline_stage !== stageFilter) return false
    if (sourceFilter && lead.source !== sourceFilter) return false
    if (dispositionFilter === "__none__" && lead.disposition_name) return false
    if (dispositionFilter === "__has__" && !lead.disposition_name) return false
    if (
      dispositionFilter
      && dispositionFilter !== "__none__"
      && dispositionFilter !== "__has__"
      && lead.disposition_name !== dispositionFilter
    ) return false
    return true
  }, [search, stageFilter, sourceFilter, dispositionFilter])

  const sortLeads = useCallback((list) => {
    const copy = [...list]
    if (sortBy === "name") {
      copy.sort((a, b) => (a.name || "").localeCompare(b.name || ""))
    } else if (sortBy === "soonest") {
      copy.sort((a, b) => {
        const fa = a.follow_up_at || "9999"
        const fb = b.follow_up_at || "9999"
        return fa.localeCompare(fb)
      })
    }
    return copy
  }, [sortBy])

  const visibleBuckets = useMemo(() => {
    if (!data?.buckets) return {}
    const out = {}
    for (const b of QUEUE_BUCKETS) {
      if (bucketFilter === "called_today") {
        out[b.id] = []
        continue
      }
      if (bucketFilter !== "all" && bucketFilter !== b.id) {
        out[b.id] = []
        continue
      }
      out[b.id] = sortLeads((data.buckets[b.id] || []).filter(filterLead))
    }
    if (bucketFilter === "called_today") {
      out.called_today = sortLeads((data.buckets.called_today || []).filter(filterLead))
    } else if (bucketFilter === "all") {
      out.called_today = []
    } else {
      out.called_today = []
    }
    return out
  }, [data, bucketFilter, filterLead, sortLeads])

  const totalVisible = useMemo(
    () => Object.values(visibleBuckets).reduce((n, arr) => n + arr.length, 0),
    [visibleBuckets],
  )

  const acwId = data?.acw_pending_lead_id

  const findAcwBucket = useCallback(() => {
    if (!acwId || !data?.buckets) return null
    for (const key of [...QUEUE_BUCKETS.map((b) => b.id), "called_today"]) {
      if ((data.buckets[key] || []).some((l) => l.id === acwId)) return key
    }
    return null
  }, [acwId, data])

  const focusAcwLead = useCallback(() => {
    if (!acwId) return
    const bucket = findAcwBucket()
    setSearch("")
    setStageFilter("")
    setSourceFilter("")
    setDispositionFilter("")
    if (bucket === "called_today") setBucketFilter("called_today")
    else setBucketFilter("all")
    acwFocusPending.current = true
    setHighlightAcw(true)
  }, [acwId, findAcwBucket])

  useEffect(() => {
    if (!acwFocusPending.current || !acwId) return
    const el = document.querySelector(`[data-testid="today-card-${acwId}"]`)
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" })
      acwFocusPending.current = false
      const t = setTimeout(() => setHighlightAcw(false), 2000)
      return () => clearTimeout(t)
    }
  }, [acwId, visibleBuckets, bucketFilter])

  if (!data) return <PageLoader />
  const counts = data.counts || {}
  const acwCount = data.tab_counts?.acw_pending ?? (acwId ? 1 : 0)
  const overdueCount = counts.overdue || 0
  const queueTotal = (counts.overdue || 0) + (counts.due_today || 0)
    + (counts.assigned_today || 0) + (counts.upcoming || 0)

  const handleBucketChip = (id) => {
    if (id === "all") {
      setBucketFilter("all")
      return
    }
    setBucketFilter(bucketFilter === id ? "all" : id)
  }

  const countChips = [
    { id: "all", label: "All", value: queueTotal, accent: "bg-white text-slate-800 ring-slate-200" },
    { id: "overdue", label: "Overdue", value: counts.overdue || 0, accent: "bg-red-50 text-red-700 ring-red-200" },
    { id: "due_today", label: "Due today", value: counts.due_today || 0, accent: "bg-amber-50 text-amber-800 ring-amber-200" },
    { id: "assigned_today", label: "Assigned today", value: counts.assigned_today || 0, accent: "bg-sky-50 text-sky-800 ring-sky-200" },
    { id: "upcoming", label: "Upcoming", value: counts.upcoming || 0, accent: "bg-slate-50 text-slate-700 ring-slate-200" },
    { id: "called_today", label: "Called today", value: counts.called_today || 0, accent: "bg-emerald-50 text-emerald-800 ring-emerald-200" },
  ]

  return (
    <div data-testid="today-calls-page" className="space-y-1.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <h1 className="font-display text-lg font-bold text-slate-900">Today Calls</h1>
          <p className="text-xs text-slate-500">Calls workbench · {data.date}</p>
        </div>
        {acwId && (
          <Button size="sm" variant="outline" className="h-8" onClick={completeAcw} data-testid="complete-acw-btn">
            <CheckCircle2 size={14} className="mr-1.5" /> Complete ACW
          </Button>
        )}
      </div>

      <div className="flex flex-wrap gap-1" data-testid="kpi-strip" role="group" aria-label="Queue counts">
        {countChips.map((kpi) => {
          const isActive = bucketFilter === kpi.id
          return (
            <button
              key={kpi.id}
              type="button"
              onClick={() => handleBucketChip(kpi.id)}
              className={cn(
                "rounded-md px-2 py-1 text-left ring-1 ring-inset transition-colors",
                kpi.accent,
                isActive && "ring-2 ring-sky-500",
              )}
              data-testid={`kpi-${kpi.id}`}
              aria-pressed={isActive}
              aria-label={`${kpi.label}: ${kpi.value}`}
            >
              <p className="text-[10px] font-semibold uppercase tracking-wide opacity-80 leading-none">{kpi.label}</p>
              <p className="font-display text-sm font-bold tabular-nums leading-tight mt-0.5">{kpi.value}</p>
            </button>
          )
        })}
        <button
          type="button"
          className={cn(
            "rounded-md bg-amber-50 px-2 py-1 text-left ring-1 ring-inset ring-amber-200",
            acwCount > 0 && "ring-amber-300",
          )}
          data-testid="kpi-acw"
          onClick={focusAcwLead}
          disabled={!acwId}
          aria-label={`ACW: ${acwCount}`}
        >
          <p className="text-[10px] font-semibold uppercase tracking-wide text-amber-800 leading-none">ACW</p>
          <p className="font-display text-sm font-bold tabular-nums leading-tight mt-0.5 text-amber-900">{acwCount}</p>
        </button>
      </div>

      {acwId && (
        <div
          className="flex flex-wrap items-center gap-2 rounded-md border border-amber-200 bg-amber-50 px-2.5 py-1.5 text-xs text-amber-800"
          data-testid="acw-banner"
        >
          <AlertTriangle size={14} className="shrink-0" />
          <span className="min-w-0 flex-1">After-call work pending — complete anytime. Calling other leads is not blocked.</span>
          <Button size="sm" variant="outline" className="h-7 shrink-0" onClick={completeAcw} data-testid="complete-acw-banner-btn">
            Complete ACW
          </Button>
          <Button size="sm" variant="ghost" className="h-7 shrink-0 text-amber-900" onClick={focusAcwLead} data-testid="view-acw-btn">
            View ACW
          </Button>
        </div>
      )}

      {overdueCount > 0 && (
        <div
          className="flex items-center gap-2 rounded-md border border-red-200 bg-red-50 px-2.5 py-1.5 text-xs text-red-800"
          data-testid="overdue-banner"
        >
          <AlertTriangle size={14} />
          {overdueCount} overdue callback{overdueCount === 1 ? "" : "s"} need attention.
        </div>
      )}

      <div
        className="flex flex-wrap items-center gap-x-2 gap-y-1.5 rounded-lg border border-slate-200 bg-white p-1.5 shadow-sm"
        data-testid="workbench-filters"
      >
        <div className="relative min-w-[10rem] flex-1">
          <Search size={14} className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-slate-400" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search name or phone"
            className="h-8 pl-8"
            data-testid="filter-search"
            aria-label="Search name or phone"
          />
        </div>
        <div className="w-32 shrink-0">
          <SearchableSelect
            value={stageFilter || "all"}
            onChange={(v) => setStageFilter(v === "all" ? "" : v)}
            options={[
              { value: "all", label: "All stages" },
              ...STAGES.map((s) => ({ value: s, label: s })),
            ]}
            placeholder="All stages"
            testId="filter-stage"
            className="h-8"
          />
        </div>
        <div className="w-32 shrink-0">
          <SearchableSelect
            value={sourceFilter || "all"}
            onChange={(v) => setSourceFilter(v === "all" ? "" : v)}
            options={[
              { value: "all", label: "All sources" },
              ...sources.map((s) => ({ value: s, label: s })),
            ]}
            placeholder="All sources"
            testId="filter-source"
            className="h-8"
          />
        </div>
        <div className="min-w-[9rem] w-40 shrink-0">
          <SearchableSelect
            value={dispositionFilter || "all"}
            onChange={(v) => setDispositionFilter(v === "all" ? "" : v)}
            options={[
              { value: "all", label: "All dispositions" },
              { value: "__none__", label: "No disposition" },
              { value: "__has__", label: "Has disposition" },
              ...dispositionNames.map((d) => ({ value: d, label: d })),
            ]}
            placeholder="All dispositions"
            testId="filter-disposition"
            className="h-8"
          />
        </div>
        <div className="w-28 shrink-0">
          <SearchableSelect
            value={sortBy}
            onChange={setSortBy}
            options={SORTS.map((s) => ({ value: s.id, label: s.label }))}
            placeholder="Sort"
            testId="filter-sort"
            className="h-8"
          />
        </div>
      </div>

      {totalVisible === 0 ? (
        <EmptyState
          icon={PhoneOutgoing}
          title="No calls in this queue"
          description="Assigned leads and follow-ups in your scope will appear here."
          testid="today-empty"
        />
      ) : (
        <div className="space-y-3">
          {DISPLAY_SECTIONS.map((section) => {
            const items = visibleBuckets[section.id] || []
            if (bucketFilter === "called_today") {
              if (section.id !== "called_today") return null
            } else if (section.id === "called_today") {
              return null
            } else if (bucketFilter !== "all" && bucketFilter !== section.id) {
              return null
            }
            if (bucketFilter === "all" && items.length === 0) return null
            return (
              <section key={section.id} data-testid={`section-${section.id}`}>
                <div className="sticky top-0 z-10 mb-1 flex items-center gap-1.5 bg-slate-50/95 py-0.5 backdrop-blur-sm">
                  <h2 className="font-display text-xs font-bold text-slate-800">{section.label}</h2>
                  <span className="rounded-full bg-slate-200 px-1.5 py-0 text-[10px] font-semibold text-slate-600">
                    {items.length}
                  </span>
                </div>
                {items.length === 0 ? (
                  <p className="text-xs text-slate-400" data-testid={`section-empty-${section.id}`}>
                    Nothing in this bucket
                  </p>
                ) : (
                  <div className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-3">
                    {items.map((l) => {
                      const urgency = urgencyLabel(l)
                      const isAcwPending = acwId === l.id
                      return (
                        <div
                          key={l.id}
                          className={cn(
                            "rounded-md border bg-white p-2.5 shadow-sm transition-shadow duration-200 hover:shadow-md",
                            isAcwPending ? "border-amber-300 ring-1 ring-amber-200" : "border-slate-200",
                            highlightAcw && isAcwPending && "ring-2 ring-amber-400",
                            l.queue_reason === "overdue" && "border-l-4 border-l-red-500",
                            l.queue_reason === "due_today" && "border-l-4 border-l-amber-400",
                            l.queue_reason === "called_today" && "border-l-4 border-l-emerald-500",
                          )}
                          data-testid={`today-card-${l.id}`}
                          data-queue-reason={l.queue_reason}
                        >
                          <div className="flex items-start gap-2">
                            <div className="min-w-0 flex-1">
                              <LeadPhoneLink leadId={l.id} onOpen={setLead360Id} asName testId={`today-name-${l.id}`}>
                                {l.name}
                              </LeadPhoneLink>
                              <div className="mt-0.5">
                                <LeadPhoneLink leadId={l.id} onOpen={setLead360Id} testId={`today-phone-${l.id}`}>
                                  {l.phone}
                                </LeadPhoneLink>
                              </div>
                              <div className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[11px] text-slate-400">
                                <span>{l.source || "—"}</span>
                                <span>·</span>
                                <span>{l.pipeline_stage || "New"}</span>
                                {l.city && (
                                  <>
                                    <span>·</span>
                                    <span>{l.city}</span>
                                  </>
                                )}
                              </div>
                              <div className="mt-1 flex flex-wrap gap-1">
                                {isAcwPending && <StatusPill color="amber">ACW</StatusPill>}
                                {urgency && (
                                  <StatusPill color={bucketPill(l.queue_reason)}>{urgency}</StatusPill>
                                )}
                                {l.disposition_name ? (
                                  <StatusPill color={l.carry_forward ? "sky" : "amber"}>
                                    {l.disposition_name}
                                  </StatusPill>
                                ) : (
                                  <StatusPill color="slate">Fresh</StatusPill>
                                )}
                              </div>
                              <LastRemarks
                                notes={l.last_notes}
                                compact
                                showLabel
                                className="mt-1.5"
                                testId={`today-last-remarks-${l.id}`}
                              />
                            </div>
                            <div className="flex shrink-0 flex-col gap-1">
                              <Button
                                size="sm"
                                className="h-7 bg-sky-500 px-2 hover:bg-sky-600"
                                onClick={() => openLog(l)}
                                data-testid={`log-call-btn-${l.id}`}
                                aria-label={`Log call for ${l.name}`}
                              >
                                <PhoneCall size={13} className="mr-1" />
                                Log
                              </Button>
                              {isAcwPending && (
                                <Button
                                  size="sm"
                                  variant="outline"
                                  className="h-7 px-2"
                                  onClick={completeAcw}
                                  data-testid={`complete-acw-card-${l.id}`}
                                >
                                  <CheckCircle2 size={13} className="mr-1" />
                                  ACW
                                </Button>
                              )}
                            </div>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}
              </section>
            )
          })}
        </div>
      )}

      <Dialog open={!!active} onOpenChange={(o) => !o && setActive(null)}>
        <DialogContent className="bg-white" data-testid="log-call-dialog">
          <DialogHeader>
            <DialogTitle>Log Call — {active?.name}</DialogTitle>
            <DialogDescription>{active?.phone}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <SearchableSelect
              value={form.disposition_id}
              onChange={(v) => {
                const disp = dispositions.find((d) => d.id === v)
                const mapped = mappedStageForDisposition(disp)
                const nextStage = mapped || form.pipeline_stage
                let follow_up_at = form.follow_up_at
                if (isConvertDisposition(disp) || isTerminalStage(nextStage)) {
                  follow_up_at = ""
                } else if (isCallBackDisposition(disp)) {
                  follow_up_at = nowDatetimeLocalValue()
                }
                setForm({
                  ...form,
                  disposition_id: v,
                  pipeline_stage: nextStage,
                  follow_up_at,
                })
              }}
              options={dispositions.map((d) => ({
                value: d.id,
                label: d.name,
                color: d.color,
                requires_acw: d.requires_acw,
              }))}
              placeholder="Choose outcome"
              searchPlaceholder="Search dispositions…"
              label="Disposition"
              testId="disposition-select"
              renderItem={(o) => (
                <span className="flex items-center gap-2">
                  <span className="h-2.5 w-2.5 rounded-full shrink-0" style={{ background: o.color }} />
                  {o.label}
                  {o.requires_acw && <span className="text-[10px] text-amber-600">ACW</span>}
                </span>
              )}
            />
            <div className="grid grid-cols-2 gap-3">
              <SearchableSelect
                value={form.pipeline_stage}
                onChange={(v) => setForm({
                  ...form,
                  pipeline_stage: v,
                  follow_up_at: isTerminalStage(v) ? "" : form.follow_up_at,
                })}
                options={STAGES.map((s) => ({ value: s, label: s }))}
                placeholder="Select stage"
                searchPlaceholder="Search stages…"
                label="Pipeline stage"
                testId="stage-select"
                disabled={Boolean(mappedStageForDisposition(
                  dispositions.find((d) => d.id === form.disposition_id),
                ))}
              />
              <div>
                <Label htmlFor="today-duration">Duration (sec)</Label>
                <Input
                  id="today-duration"
                  type="number"
                  value={form.duration}
                  className="mt-1 focus-visible:ring-sky-500"
                  onChange={(e) => setForm({ ...form, duration: e.target.value })}
                  data-testid="duration-input"
                />
              </div>
            </div>
            {(() => {
              const disp = dispositions.find((d) => d.id === form.disposition_id)
              const converts = isConvertDisposition(disp)
              const fuDisabled = converts || isTerminalStage(form.pipeline_stage)
              const callBack = isCallBackDisposition(disp)
              return (
                <div>
                  <Label htmlFor="today-followup">
                    Follow-up date/time{callBack && !fuDisabled ? " *" : fuDisabled ? "" : " (optional)"}
                  </Label>
                  <Input
                    id="today-followup"
                    type="datetime-local"
                    value={form.follow_up_at}
                    className="mt-1 focus-visible:ring-sky-500"
                    onChange={(e) => setForm({ ...form, follow_up_at: e.target.value })}
                    data-testid="followup-input"
                    disabled={fuDisabled}
                    required={callBack && !fuDisabled}
                  />
                  {fuDisabled ? (
                    <p className="mt-1 text-xs text-slate-500">No follow-up after conversion / closed stage</p>
                  ) : callBack ? (
                    <p className="mt-1 text-xs text-slate-500">Scheduled for next follow-up (no ACW)</p>
                  ) : (
                    <p className="mt-1 text-xs text-slate-500">Leave blank to clear previous follow-up</p>
                  )}
                </div>
              )
            })()}
            {isConvertDisposition(dispositions.find((d) => d.id === form.disposition_id)) && (
              <div data-testid="convert-deposit-section">
                <Label htmlFor="today-deposit">Deposit amount (₹)</Label>
                <Input
                  id="today-deposit"
                  type="number"
                  min={0}
                  step="0.01"
                  value={form.deposit_amount}
                  className="mt-1 focus-visible:ring-sky-500"
                  placeholder="Optional"
                  onChange={(e) => setForm({ ...form, deposit_amount: e.target.value })}
                  data-testid="convert-deposit-amount"
                  aria-label="Deposit amount"
                />
                <p className="mt-1 text-xs text-slate-500">Optional — posts to Finance Ledger</p>
              </div>
            )}
            <div>
              <LastRemarks
                notes={active?.last_notes}
                showLabel
                className="rounded-md border border-slate-100 bg-slate-50 p-2.5"
                testId="log-call-last-remarks"
              />
            </div>
            <div>
              <Label htmlFor="today-calls-remarks">Remarks</Label>
              <Textarea
                id="today-calls-remarks"
                value={form.notes}
                className="mt-1 focus-visible:ring-sky-500"
                rows={3}
                onChange={(e) => setForm({ ...form, notes: e.target.value })}
                data-testid="remarks-input"
                aria-label="Remarks"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setActive(null)}>Cancel</Button>
            <Button className="bg-sky-500 hover:bg-sky-600" onClick={submit} data-testid="submit-call-btn">
              Save Disposition
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Lead360Sheet
        leadId={lead360Id}
        onClose={() => setLead360Id(null)}
        onLogged={() => load()}
      />
    </div>
  )
}
