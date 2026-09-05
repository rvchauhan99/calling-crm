import { useEffect, useState, useCallback, useMemo } from "react"
import { useSearchParams } from "react-router-dom"
import api, { formatApiError } from "@/lib/api"
import { useAuth } from "@/context/AuthContext"
import { PageHeader, PageLoader, StatusPill, EmptyState } from "@/components/common"
import { FilterToolbar, FilterField } from "@/components/filters/FilterToolbar"
import { useDebouncedParam } from "@/hooks/useDebouncedParam"
import { PipelineLogCallDialog, PIPELINE_STAGES } from "@/components/pipeline/PipelineLogCallDialog"
import { Lead360Sheet } from "@/components/leads/Lead360Sheet"
import { LeadPhoneLink } from "@/components/leads/LeadPhoneLink"
import { LastRemarks } from "@/components/leads/LastRemarks"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { SearchableSelect } from "@/components/ui/searchable-select"
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table"
import { toast } from "sonner"
import { Search, LayoutGrid, List, PhoneCall, Kanban } from "lucide-react"
import { cn } from "@/lib/utils"

const COLORS = {
  New: "sky", Contacted: "blue", Qualified: "sky", Proposal: "amber", Won: "emerald", Lost: "slate",
}

export default function Pipeline() {
  const { can, dataScope } = useAuth()
  const isOwnScope = dataScope === "OWN"
  const canEdit = can("pipeline:edit")
  const canLog = can("today_calls:log")

  const [params, setParams] = useSearchParams()
  const view = params.get("view") === "list" ? "list" : "kanban"
  const search = params.get("search") || ""
  const source = params.get("source") || ""
  const disposition = params.get("disposition") || ""
  const assignedTo = params.get("assigned_to") || ""

  const [data, setData] = useState(null)
  const [filterOptions, setFilterOptions] = useState(null)
  const [agents, setAgents] = useState([])
  const [dispositions, setDispositions] = useState([])
  const [dragId, setDragId] = useState(null)
  const [moveTarget, setMoveTarget] = useState(null)
  const [logLead, setLogLead] = useState(null)
  const [lead360Id, setLead360Id] = useState(null)

  const setParam = useCallback((k, v) => {
    const p = new URLSearchParams(params)
    if (v) p.set(k, v)
    else p.delete(k)
    setParams(p)
  }, [params, setParams])

  const commitSearch = useCallback((v) => setParam("search", v.trim()), [setParam])
  const [searchLocal, setSearchLocal] = useDebouncedParam(search, commitSearch)

  const load = useCallback(async () => {
    const p = new URLSearchParams()
    if (search) p.set("search", search)
    if (source) p.set("source", source)
    if (disposition) p.set("disposition", disposition)
    if (!isOwnScope && assignedTo) p.set("assigned_to", assignedTo)
    const qs = p.toString()
    const { data: board } = await api.get(`/pipeline${qs ? `?${qs}` : ""}`)
    setData(board)
  }, [search, source, disposition, assignedTo, isOwnScope])

  useEffect(() => { load().catch(() => {}) }, [load])

  useEffect(() => {
    api.get("/leads/filter-options").then((r) => setFilterOptions(r.data)).catch(() => {})
    api.get("/dispositions").then((r) => {
      setDispositions((r.data.dispositions || []).filter((d) => d.active))
    }).catch(() => {})
    if (!isOwnScope) {
      api.get("/dashboard/filter-options").then((r) => setAgents(r.data.agents || [])).catch(() => {})
    }
  }, [isOwnScope])

  const clearFilters = () => {
    const p = new URLSearchParams()
    if (view === "list") p.set("view", "list")
    setParams(p)
    setSearchLocal("")
  }

  const chips = useMemo(() => {
    const list = []
    if (search) list.push({ key: "search", label: `Search: ${search}`, onRemove: () => setParam("search", "") })
    if (source) list.push({ key: "source", label: `Source: ${source}`, onRemove: () => setParam("source", "") })
    if (disposition) {
      list.push({
        key: "disposition",
        label: `Disposition: ${disposition === "__none__" ? "None" : disposition}`,
        onRemove: () => setParam("disposition", ""),
      })
    }
    if (!isOwnScope && assignedTo) {
      const name = agents.find((a) => a.id === assignedTo)?.name || assignedTo
      list.push({ key: "assigned_to", label: `Agent: ${name}`, onRemove: () => setParam("assigned_to", "") })
    }
    return list
  }, [search, source, disposition, assignedTo, isOwnScope, agents, setParam])

  const findLead = (id) => {
    if (!data?.board) return null
    for (const stage of data.stages || PIPELINE_STAGES) {
      const hit = (data.board[stage] || []).find((l) => l.id === id)
      if (hit) return hit
    }
    return null
  }

  const handleDrop = (stage) => {
    if (!canEdit || !dragId) return
    const lead = findLead(dragId)
    if (!lead) return
    if (lead.pipeline_stage === stage) {
      setDragId(null)
      return
    }
    setMoveTarget({ lead, stage })
    setDragId(null)
  }

  const submitLog = async (payload) => {
    const lead = moveTarget?.lead || logLead
    if (!lead) return
    if (!payload.disposition_id) {
      toast.error("Select a disposition")
      return
    }
    const disp = dispositions.find((d) => d.id === payload.disposition_id)
    const stage = payload.pipeline_stage
    const converts = Boolean(disp?.converts_to_client || disp?.name === "Converted")
    const terminal = stage === "Won" || stage === "Lost" || converts
    const callBack = disp?.name === "Call Back"
    const fuRequired = !terminal && (callBack || Boolean(moveTarget))
    if (fuRequired && !payload.follow_up_at) {
      toast.error(callBack ? "Follow-up required for Call Back" : "Follow-up date/time is required")
      return
    }
    try {
      const { data: res } = await api.post("/calls/log", {
        lead_id: lead.id,
        disposition_id: payload.disposition_id,
        outcome: "connected",
        notes: payload.notes || "",
        duration: payload.duration || 0,
        follow_up_at: terminal ? null : (payload.follow_up_at || null),
        pipeline_stage: stage,
        ...(payload.deposit_amount != null ? { deposit_amount: payload.deposit_amount } : {}),
      })
      if (res.converted) {
        toast.success(res.deposit_posted
          ? "Lead converted to client · Deposit posted"
          : "Lead converted to client")
      } else toast.success(moveTarget ? `Moved to ${stage}` : "Call logged")
      setMoveTarget(null)
      setLogLead(null)
      load()
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail))
    }
  }

  const openDetail = (id) => setLead360Id(id)

  const flatLeads = useMemo(() => {
    if (!data?.board) return []
    return (data.stages || []).flatMap((s) => data.board[s] || [])
  }, [data])

  if (!data) return <PageLoader />

  return (
    <div data-testid="pipeline-page" className="space-y-3">
      <PageHeader
        title="Pipeline"
        subtitle={`${data.total ?? flatLeads.length} leads · drag to move (logs call + follow-up)`}
        actions={(
          <div className="flex gap-1.5">
            <Button
              size="sm"
              variant={view === "kanban" ? "default" : "outline"}
              className={cn("h-8", view === "kanban" && "bg-sky-500 hover:bg-sky-600")}
              onClick={() => setParam("view", "")}
              data-testid="view-kanban"
            >
              <LayoutGrid size={14} className="mr-1.5" /> Kanban
            </Button>
            <Button
              size="sm"
              variant={view === "list" ? "default" : "outline"}
              className={cn("h-8", view === "list" && "bg-sky-500 hover:bg-sky-600")}
              onClick={() => setParam("view", "list")}
              data-testid="view-list"
            >
              <List size={14} className="mr-1.5" /> List
            </Button>
          </div>
        )}
      />

      <FilterToolbar
        testId="pipeline-filters"
        search={(
          <>
            <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
            <Input
              value={searchLocal}
              onChange={(e) => setSearchLocal(e.target.value)}
              placeholder="Search name, phone, email…"
              className="h-8 pl-8"
              data-testid="pipeline-search"
              aria-label="Search leads"
            />
          </>
        )}
        fields={(
          <>
            <FilterField label="Source" className="w-36">
              <SearchableSelect
                value={source || "all"}
                onChange={(v) => setParam("source", v === "all" ? "" : v)}
                options={[
                  { value: "all", label: "All sources" },
                  ...(filterOptions?.sources || []).map((s) => ({ value: s, label: s })),
                ]}
                placeholder="All sources"
                testId="pipeline-filter-source"
                className="h-8"
              />
            </FilterField>
            <FilterField label="Disposition" className="min-w-[10rem] w-44">
              <SearchableSelect
                value={disposition || "all"}
                onChange={(v) => setParam("disposition", v === "all" ? "" : v)}
                options={[
                  { value: "all", label: "All dispositions" },
                  { value: "__none__", label: "No disposition" },
                  ...(filterOptions?.dispositions || []).map((d) => ({ value: d.name, label: d.name })),
                ]}
                placeholder="All dispositions"
                testId="pipeline-filter-disposition"
                className="h-8"
              />
            </FilterField>
            {!isOwnScope && agents.length > 0 && (
              <FilterField label="Agent" className="w-40">
                <SearchableSelect
                  value={assignedTo || "all"}
                  onChange={(v) => setParam("assigned_to", v === "all" ? "" : v)}
                  options={[
                    { value: "all", label: "All agents" },
                    ...agents.map((a) => ({ value: a.id, label: a.name })),
                  ]}
                  placeholder="All agents"
                  testId="pipeline-filter-agent"
                  className="h-8"
                />
              </FilterField>
            )}
          </>
        )}
        chips={chips}
        onClearAll={chips.length ? clearFilters : undefined}
      />

      {view === "kanban" ? (
        <div className="flex gap-3 overflow-x-auto pb-4">
          {(data.stages || PIPELINE_STAGES).map((stage) => {
            const items = data.board[stage] || []
            return (
              <div
                key={stage}
                className="w-72 flex-shrink-0"
                data-testid={`stage-col-${stage}`}
                onDragOver={(e) => e.preventDefault()}
                onDrop={() => handleDrop(stage)}
              >
                <div className="mb-2 flex items-center justify-between rounded-md border border-slate-200 bg-white px-3 py-2 shadow-sm">
                  <span className="font-display text-sm font-semibold text-slate-700">{stage}</span>
                  <StatusPill color={COLORS[stage] || "slate"}>{items.length}</StatusPill>
                </div>
                <div className="min-h-[120px] space-y-2">
                  {items.map((l) => (
                    <div
                      key={l.id}
                      role="button"
                      tabIndex={0}
                      draggable={canEdit}
                      onDragStart={() => setDragId(l.id)}
                      onDragEnd={() => setDragId(null)}
                      onClick={() => openDetail(l.id)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault()
                          openDetail(l.id)
                        }
                      }}
                      className={cn(
                        "rounded-lg border border-slate-200 bg-white p-3 shadow-sm transition-shadow hover:shadow-md",
                        canEdit ? "cursor-grab active:cursor-grabbing" : "cursor-pointer",
                      )}
                      data-testid={`pipeline-card-${l.id}`}
                      aria-label={`${l.name} in ${stage}`}
                    >
                      <p className="text-sm font-medium text-slate-800">{l.name}</p>
                      <p className="tabular text-xs text-slate-500">{l.phone}</p>
                      <div className="mt-2 flex flex-wrap items-center gap-1.5">
                        <span className="text-[11px] text-slate-400">{l.source || "—"}</span>
                        {l.assigned_name && (
                          <span className="text-[11px] text-slate-400">· {l.assigned_name}</span>
                        )}
                      </div>
                      <div className="mt-2 flex flex-wrap gap-1">
                        {l.disposition_name ? (
                          <StatusPill color={l.carry_forward ? "sky" : "amber"}>{l.disposition_name}</StatusPill>
                        ) : (
                          <StatusPill color="slate">Fresh</StatusPill>
                        )}
                        {l.follow_up_at && (
                          <StatusPill color="amber">
                            FU {new Date(l.follow_up_at).toLocaleDateString("en-IN")}
                          </StatusPill>
                        )}
                      </div>
                      <LastRemarks
                        notes={l.last_notes}
                        compact
                        className="mt-1.5 text-xs"
                        testId={`pipeline-card-last-remarks-${l.id}`}
                      />
                      {canLog && (
                        <Button
                          size="sm"
                          variant="outline"
                          className="mt-2 h-7 w-full"
                          title="Log call"
                          onClick={(e) => {
                            e.stopPropagation()
                            setLogLead(l)
                          }}
                          onKeyDown={(e) => e.stopPropagation()}
                          data-testid={`kanban-call-${l.id}`}
                        >
                          <PhoneCall size={12} className="mr-1" />
                          Call
                        </Button>
                      )}
                    </div>
                  ))}
                  {items.length === 0 && (
                    <div className="rounded-lg border border-dashed border-slate-200 py-6 text-center text-xs text-slate-300">
                      Empty
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      ) : (
        <div className="rounded-lg border border-slate-200 bg-white shadow-sm">
          {flatLeads.length === 0 ? (
            <EmptyState icon={Kanban} title="No leads" description="Adjust filters or assign leads to see the pipeline." testid="pipeline-empty" />
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="bg-slate-50">
                  <TableHead>Name</TableHead>
                  <TableHead>Phone</TableHead>
                  <TableHead>Stage</TableHead>
                  <TableHead>Disposition</TableHead>
                  <TableHead>Last Remarks</TableHead>
                  <TableHead>Assigned</TableHead>
                  <TableHead>Follow-up</TableHead>
                  <TableHead className="w-28" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {flatLeads.map((l) => (
                  <TableRow key={l.id} data-testid={`pipeline-row-${l.id}`}>
                    <TableCell>
                      <LeadPhoneLink leadId={l.id} onOpen={openDetail} asName testId={`pipeline-name-${l.id}`}>
                        {l.name}
                      </LeadPhoneLink>
                    </TableCell>
                    <TableCell>
                      <LeadPhoneLink leadId={l.id} onOpen={openDetail} testId={`pipeline-phone-${l.id}`}>
                        {l.phone}
                      </LeadPhoneLink>
                    </TableCell>
                    <TableCell>
                      {canEdit ? (
                        <select
                          className="h-8 rounded-md border border-slate-200 bg-white px-2 text-sm"
                          value={l.pipeline_stage || "New"}
                          data-testid={`stage-select-${l.id}`}
                          onChange={(e) => {
                            const stage = e.target.value
                            if (stage === l.pipeline_stage) return
                            setMoveTarget({ lead: l, stage })
                          }}
                        >
                          {PIPELINE_STAGES.map((s) => (
                            <option key={s} value={s}>{s}</option>
                          ))}
                        </select>
                      ) : (
                        <StatusPill color={COLORS[l.pipeline_stage] || "slate"}>{l.pipeline_stage}</StatusPill>
                      )}
                    </TableCell>
                    <TableCell>{l.disposition_name || "—"}</TableCell>
                    <TableCell>
                      <LastRemarks notes={l.last_notes} testId={`pipeline-last-remarks-${l.id}`} />
                    </TableCell>
                    <TableCell className="text-slate-500">{l.assigned_name || "—"}</TableCell>
                    <TableCell className="text-xs text-slate-500">
                      {l.follow_up_at ? new Date(l.follow_up_at).toLocaleString("en-IN") : "—"}
                    </TableCell>
                    <TableCell>
                      {canLog && (
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-7"
                          onClick={() => setLogLead(l)}
                          data-testid={`list-log-call-${l.id}`}
                        >
                          <PhoneCall size={12} className="mr-1" /> Log
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </div>
      )}

      <PipelineLogCallDialog
        open={!!moveTarget}
        lead={moveTarget?.lead}
        targetStage={moveTarget?.stage}
        dispositions={dispositions}
        mode="move"
        onClose={() => setMoveTarget(null)}
        onSubmit={submitLog}
      />

      <PipelineLogCallDialog
        open={!!logLead}
        lead={logLead}
        dispositions={dispositions}
        mode="log"
        onClose={() => setLogLead(null)}
        onSubmit={submitLog}
      />

      <Lead360Sheet
        leadId={lead360Id}
        onClose={() => setLead360Id(null)}
        onLogged={() => load()}
      />
    </div>
  )
}
