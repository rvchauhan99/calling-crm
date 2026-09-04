import { useCallback, useEffect, useMemo, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import api from "@/lib/api"
import { useAuth } from "@/context/AuthContext"
import { PageHeader, PageLoader, Money } from "@/components/common"
import { SearchableSelect } from "@/components/ui/searchable-select"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { FilterToolbar, FilterField } from "@/components/filters/FilterToolbar"
import {
  PanelHeader, KpiCard, MiniBar, InsightCard, buildLeadHref,
  monthStartISO, todayISO, startOfWeekISO, monthsAgoISO,
} from "@/components/dashboard/atoms"
import { ChevronDown, ChevronUp, Filter } from "lucide-react"
import { cn } from "@/lib/utils"
import {
  BarChart, Bar, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer, Legend, AreaChart, Area,
} from "recharts"

const defaultFilters = () => ({
  from: monthStartISO(),
  to: todayISO(),
  status: "",
  source: "",
  stage: "",
  disposition: "",
  assignment_status: "",
  assigned_to: "",
})

const PRESETS = [
  { id: "today", label: "Today", apply: () => ({ from: todayISO(), to: todayISO() }) },
  { id: "week", label: "This Week", apply: () => ({ from: startOfWeekISO(), to: todayISO() }) },
  { id: "month", label: "This Month", apply: () => ({ from: monthStartISO(), to: todayISO() }) },
  { id: "3m", label: "Last 3M", apply: () => ({ from: monthsAgoISO(3), to: todayISO() }) },
]

const STATUS_TABS = [
  { id: "all", label: "All", value: "" },
  { id: "active", label: "Active", value: "active" },
  { id: "inactive", label: "Inactive", value: "inactive" },
  { id: "converted", label: "Converted", value: "converted" },
]

const FILTER_KEYS = ["from", "to", "status", "source", "stage", "disposition", "assignment_status", "assigned_to", "preset"]

const filtersFromParams = (params) => {
  const base = defaultFilters()
  FILTER_KEYS.forEach((k) => {
    if (k === "preset") return
    const v = params.get(k)
    if (v) base[k] = v
  })
  return base
}

export default function Dashboard() {
  const { user, dataScope } = useAuth()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const isAffiliate = user?.user_type === "affiliate"
  const isOwnScope = dataScope === "OWN"

  const [filters, setFilters] = useState(() => filtersFromParams(params))
  const [activePreset, setActivePreset] = useState(() => params.get("preset") || "month")
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [options, setOptions] = useState(null)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [responseView, setResponseView] = useState("leads")

  const syncUrl = useCallback((next, presetId) => {
    const p = new URLSearchParams()
    const d = defaultFilters()
    Object.entries(next).forEach(([k, v]) => {
      if (!v) return
      if (k === "from" && v === d.from && (presetId === "month" || !presetId)) return
      if (k === "to" && v === d.to && (presetId === "month" || !presetId)) {
        // still write dates when non-default preset or other filters active
      }
      p.set(k, v)
    })
    if (next.from) p.set("from", next.from)
    if (next.to) p.set("to", next.to)
    if (presetId) p.set("preset", presetId)
    else p.delete("preset")
    ;["status", "source", "stage", "disposition", "assignment_status", "assigned_to"].forEach((k) => {
      if (next[k]) p.set(k, next[k])
      else p.delete(k)
    })
    setParams(p, { replace: true })
  }, [setParams])

  const loadSummary = useCallback(async (override) => {
    const f = override || filters
    setLoading(true)
    try {
      const p = new URLSearchParams()
      if (f.from) p.set("from", f.from)
      if (f.to) p.set("to", f.to)
      if (f.status) p.set("status", f.status)
      if (f.source) p.set("source", f.source)
      if (f.stage) p.set("stage", f.stage)
      if (f.disposition) p.set("disposition", f.disposition)
      if (!isOwnScope && f.assignment_status) p.set("assignment_status", f.assignment_status)
      if (!isOwnScope && f.assigned_to) p.set("assigned_to", f.assigned_to)
      const { data: summary } = await api.get(`/dashboard?${p.toString()}`)
      setData(summary)
    } catch {
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [filters, isOwnScope])

  useEffect(() => {
    api.get("/dashboard/filter-options").then((r) => setOptions(r.data)).catch(() => {})
  }, [])

  useEffect(() => {
    const initial = filtersFromParams(params)
    setFilters(initial)
    setActivePreset(params.get("preset") || "month")
    loadSummary(initial).catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handlePreset = (preset) => {
    const next = { ...filters, ...preset.apply() }
    setFilters(next)
    setActivePreset(preset.id)
    syncUrl(next, preset.id)
    loadSummary(next)
  }

  const handleStatusTab = (tab) => {
    const next = { ...filters, status: tab.value }
    setFilters(next)
    syncUrl(next, activePreset)
    loadSummary(next)
  }

  const handleApply = () => {
    setActivePreset("")
    syncUrl(filters, "")
    loadSummary(filters)
  }

  const handleReset = () => {
    const next = defaultFilters()
    setFilters(next)
    setActivePreset("month")
    syncUrl(next, "month")
    loadSummary(next)
  }

  const fc = (key, val) => setFilters((f) => ({ ...f, [key]: val }))

  const chips = useMemo(() => {
    const list = []
    if (filters.from || filters.to) list.push({ key: "date", label: `${filters.from || "…"} → ${filters.to || "…"}` })
    if (filters.status) list.push({ key: "status", label: `Status: ${filters.status}` })
    if (filters.source) list.push({ key: "source", label: `Source: ${filters.source}` })
    if (filters.stage) list.push({ key: "stage", label: `Stage: ${filters.stage}` })
    if (filters.disposition) {
      list.push({
        key: "disposition",
        label: `Disposition: ${filters.disposition === "__none__" ? "None" : filters.disposition}`,
      })
    }
    if (!isOwnScope && filters.assignment_status) {
      list.push({ key: "assignment_status", label: `Assignment: ${filters.assignment_status}` })
    }
    if (!isOwnScope && filters.assigned_to) {
      const name = options?.agents?.find((a) => a.id === filters.assigned_to)?.name || filters.assigned_to
      list.push({ key: "assigned_to", label: `Agent: ${name}` })
    }
    return list
  }, [filters, isOwnScope, options])

  const removeChip = (key) => {
    let next = { ...filters }
    let preset = activePreset
    if (key === "date") {
      next = { ...next, from: monthStartISO(), to: todayISO() }
      preset = "month"
      setActivePreset("month")
    } else {
      next = { ...next, [key]: "" }
    }
    setFilters(next)
    syncUrl(next, preset)
    loadSummary(next)
  }

  const goLeads = (extra = {}) => {
    const params = {
      status: filters.status || undefined,
      source: filters.source || undefined,
      stage: filters.stage || undefined,
      disposition: filters.disposition || undefined,
      ...extra,
    }
    if (!isOwnScope && filters.assignment_status === "unassigned") params.tab = "unassigned"
    else if (!isOwnScope) params.tab = "assigned"
    navigate(buildLeadHref(params))
  }

  if (loading && !data) return <PageLoader />
  if (!data) {
    return (
      <div data-testid="dashboard-page">
        <PageHeader title="Dashboard" subtitle="Unable to load analysis" />
      </div>
    )
  }

  const k = data.kpis
  const agingMax = Math.max(1, ...(data.aging_sla || []).map((a) => a.count))
  const funnelMax = Math.max(1, ...(data.pipeline_funnel || []).map((f) => f.count))
  const responseMax = Math.max(1, ...(data.lead_disposition_breakdown || []).map((f) => f.count))
  const rc = data.response_conversion || {}
  const trendData = (data.daily_trend || []).map((d) => ({
    ...d,
    label: d.date?.slice(5) || d.date,
  }))

  return (
    <div data-testid="dashboard-page" className="space-y-3">
      <PageHeader
        title="Dashboard"
        subtitle="Filterable operational analysis (IST)"
        actions={
          <div className="flex flex-wrap items-center gap-1.5">
            {PRESETS.map((p) => (
              <Button
                key={p.id}
                size="sm"
                variant={activePreset === p.id ? "default" : "outline"}
                className={activePreset === p.id ? "bg-sky-500 hover:bg-sky-600 h-8" : "h-8"}
                onClick={() => handlePreset(p)}
                data-testid={`preset-${p.id}`}
              >
                {p.label}
              </Button>
            ))}
            <Button size="sm" variant="outline" className="h-8" onClick={handleReset} data-testid="dashboard-reset">
              Reset
            </Button>
            <Button size="sm" className="h-8 bg-sky-500 hover:bg-sky-600" onClick={handleApply} data-testid="dashboard-apply">
              Apply
            </Button>
          </div>
        }
      />

      {!isAffiliate && (
        <>
          <div className="flex flex-wrap gap-1.5" data-testid="status-tabs">
            {STATUS_TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => handleStatusTab(t)}
                className={`rounded-full px-3 py-1 text-xs font-medium ring-1 ring-inset ${
                  (filters.status || "") === t.value
                    ? "bg-sky-500 text-white ring-sky-500"
                    : "bg-white text-slate-600 ring-slate-200 hover:bg-slate-50"
                }`}
                data-testid={`status-tab-${t.id}`}
              >
                {t.label}
              </button>
            ))}
            <Button
              size="sm"
              variant="outline"
              className="ml-auto h-7"
              onClick={() => setFiltersOpen((o) => !o)}
              data-testid="toggle-filters"
            >
              <Filter size={14} className="mr-1" />
              Filters
              {filtersOpen ? <ChevronUp size={14} className="ml-1" /> : <ChevronDown size={14} className="ml-1" />}
            </Button>
          </div>

          {filtersOpen && (
            <FilterToolbar
              testId="advanced-filters"
              fields={(
                <>
                  <FilterField label="From" className="w-36">
                    <Input type="date" value={filters.from} onChange={(e) => fc("from", e.target.value)} className="h-8" data-testid="filter-from" />
                  </FilterField>
                  <FilterField label="To" className="w-36">
                    <Input type="date" value={filters.to} onChange={(e) => fc("to", e.target.value)} className="h-8" data-testid="filter-to" />
                  </FilterField>
                  <FilterField label="Source" className="w-36">
                    <SearchableSelect
                      value={filters.source || "all"}
                      onChange={(v) => fc("source", v === "all" ? "" : v)}
                      options={[
                        { value: "all", label: "All sources" },
                        ...(options?.sources || []).map((s) => ({ value: s, label: s })),
                      ]}
                      placeholder="All sources"
                      testId="filter-source"
                      className="h-8"
                    />
                  </FilterField>
                  <FilterField label="Stage" className="w-36">
                    <SearchableSelect
                      value={filters.stage || "all"}
                      onChange={(v) => fc("stage", v === "all" ? "" : v)}
                      options={[
                        { value: "all", label: "All stages" },
                        ...(options?.stages || []).map((s) => ({ value: s, label: s })),
                      ]}
                      placeholder="All stages"
                      testId="filter-stage"
                      className="h-8"
                    />
                  </FilterField>
                  <FilterField label="Disposition" className="min-w-[10rem] w-44">
                    <SearchableSelect
                      value={filters.disposition || "all"}
                      onChange={(v) => fc("disposition", v === "all" ? "" : v)}
                      options={[
                        { value: "all", label: "All dispositions" },
                        { value: "__none__", label: "No disposition" },
                        ...(options?.dispositions || []).map((d) => ({ value: d.name, label: d.name })),
                      ]}
                      placeholder="All dispositions"
                      testId="filter-disposition"
                      className="h-8"
                    />
                  </FilterField>
                  {!isOwnScope && (
                    <FilterField label="Assignment" className="w-36">
                      <SearchableSelect
                        value={filters.assignment_status || "all"}
                        onChange={(v) => fc("assignment_status", v === "all" ? "" : v)}
                        options={[
                          { value: "all", label: "All" },
                          { value: "assigned", label: "Assigned" },
                          { value: "unassigned", label: "Unassigned" },
                        ]}
                        placeholder="Assignment"
                        testId="filter-assignment"
                        className="h-8"
                      />
                    </FilterField>
                  )}
                  {!isOwnScope && (
                    <FilterField label="Agent" className="w-40">
                      <SearchableSelect
                        value={filters.assigned_to || "all"}
                        onChange={(v) => fc("assigned_to", v === "all" ? "" : v)}
                        options={[
                          { value: "all", label: "All agents" },
                          ...(options?.agents || []).map((a) => ({ value: a.id, label: a.name })),
                        ]}
                        placeholder="All agents"
                        testId="filter-agent"
                        className="h-8"
                      />
                    </FilterField>
                  )}
                </>
              )}
              chips={chips.map((c) => ({ ...c, onRemove: () => removeChip(c.key) }))}
              onClearAll={chips.length ? handleReset : undefined}
            />
          )}

          {!filtersOpen && chips.length > 0 && (
            <div data-testid="filter-chips">
              <FilterToolbar
                testId="filter-chips-bar"
                chips={chips.map((c) => ({ ...c, onRemove: () => removeChip(c.key) }))}
                onClearAll={handleReset}
                className="mb-0 [&>div:first-child]:hidden"
              />
            </div>
          )}

          {(data.insights || []).length > 0 && (
            <div className="grid grid-cols-1 gap-2 md:grid-cols-3" data-testid="insights">
              {data.insights.map((ins, i) => (
                <InsightCard
                  key={i}
                  severity={ins.severity}
                  title={ins.title}
                  detail={ins.detail}
                  onClick={() => goLeads(ins.href_params || {})}
                />
              ))}
            </div>
          )}

          <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
            <KpiCard testId="kpi-leads" label="Total Leads" value={k.total_leads} hint={`${k.active_leads} active`} onClick={() => goLeads()} />
            <KpiCard testId="kpi-calls" label="Calls in range" value={k.calls_in_range} hint={`${k.calls_today} today · avg ${k.avg_call_duration}s`} accent="blue" onClick={() => navigate("/call-history")} />
            <KpiCard testId="kpi-converted" label="Converted" value={k.converted_leads} hint={`${k.conversion_rate}% rate`} accent="amber" onClick={() => goLeads({ status: "converted" })} />
            <KpiCard testId="kpi-conv" label="Conversion" value={`${k.conversion_rate}%`} hint={`${k.unassigned_leads} unassigned`} onClick={() => goLeads()} />
            <KpiCard testId="kpi-overdue" label="Overdue FUs" value={k.overdue_followups} accent="red" onClick={() => navigate("/followups")} />
            <KpiCard testId="kpi-clients" label="Clients" value={k.total_clients} hint={`${k.ftd_clients} FTD`} onClick={() => navigate("/clients")} />
          </div>
        </>
      )}

      {isAffiliate && (
        <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
          <KpiCard testId="kpi-clients" label="Clients" value={k.total_clients} hint={`${k.ftd_clients} FTD`} />
          <KpiCard testId="kpi-credit" label="Deposits" value={<Money value={k.ledger_credit} />} />
          <KpiCard testId="kpi-net" label="Net Balance" value={<Money value={k.net_balance} />} hint={`₹${Number(k.ledger_debit).toLocaleString("en-IN")} withdrawn`} accent="blue" />
        </div>
      )}

      {!isAffiliate && (
        <>
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4" data-testid="response-kpis">
            <KpiCard
              testId="kpi-top-response"
              label="Top response"
              value={rc.top_response || "—"}
              hint={`${rc.top_response_count || 0} leads`}
              onClick={() => rc.top_response && rc.top_response !== "No response" && goLeads({ disposition: rc.top_response })}
            />
            <KpiCard
              testId="kpi-response-coverage"
              label="With response"
              value={`${rc.response_coverage_pct ?? 0}%`}
              hint={`${rc.leads_with_response || 0} of ${k.total_leads}`}
              accent="blue"
            />
            <KpiCard
              testId="kpi-converted-response"
              label="Converted"
              value={k.converted_leads}
              hint={`${rc.converted_share_pct ?? k.conversion_rate}% of leads`}
              accent="amber"
              onClick={() => goLeads({ status: "converted" })}
            />
            <KpiCard
              testId="kpi-carry-forward"
              label="Carry-forward"
              value={`${rc.carry_forward_pct ?? 0}%`}
              hint={`${rc.carry_forward_count || 0} leads`}
            />
          </div>

          <div className="grid grid-cols-1 gap-3 lg:grid-cols-12">
            <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm lg:col-span-8" data-testid="responses-overview">
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <PanelHeader title="Responses overview" hint="Primary analysis axis" />
                <div className="flex gap-1">
                  <Button
                    size="sm"
                    variant={responseView === "leads" ? "default" : "outline"}
                    className={cn("h-7 text-xs", responseView === "leads" && "bg-sky-500 hover:bg-sky-600")}
                    onClick={() => setResponseView("leads")}
                    data-testid="response-view-leads"
                  >
                    By last response
                  </Button>
                  <Button
                    size="sm"
                    variant={responseView === "calls" ? "default" : "outline"}
                    className={cn("h-7 text-xs", responseView === "calls" && "bg-sky-500 hover:bg-sky-600")}
                    onClick={() => setResponseView("calls")}
                    data-testid="response-view-calls"
                  >
                    By calls logged
                  </Button>
                </div>
              </div>
              {responseView === "leads" ? (
                <div className="space-y-0.5" data-testid="lead-disposition-bars">
                  {(data.lead_disposition_breakdown || []).length === 0 ? (
                    <div className="py-8 text-center text-sm text-slate-400">No leads in range</div>
                  ) : (
                    (data.lead_disposition_breakdown || []).map((row) => (
                      <MiniBar
                        key={row.name}
                        label={`${row.label} · ${row.pct}%`}
                        count={row.count}
                        max={responseMax}
                        onClick={() => goLeads({
                          disposition: row.name === "__none__" ? "__none__" : row.name,
                        })}
                      />
                    ))
                  )}
                </div>
              ) : (
                <div className="h-52">
                  {(data.disposition_mix || []).length === 0 ? (
                    <div className="flex h-full items-center justify-center text-sm text-slate-400">No calls</div>
                  ) : (
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={data.disposition_mix} layout="vertical">
                        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
                        <XAxis type="number" stroke="#94a3b8" fontSize={11} tickLine={false} allowDecimals={false} />
                        <YAxis type="category" dataKey="name" width={100} stroke="#94a3b8" fontSize={10} tickLine={false} />
                        <Tooltip contentStyle={{ borderRadius: 8, border: "1px solid #e2e8f0", fontSize: 12 }} />
                        <Bar dataKey="value" name="Calls" fill="#0EA5E9" radius={[0, 4, 4, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  )}
                </div>
              )}
            </div>
            <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm lg:col-span-4">
              <PanelHeader title="Lead & call trend" hint="Selected range" />
              <div className="h-52">
                {trendData.length === 0 ? (
                  <div className="flex h-full items-center justify-center text-sm text-slate-400">No trend data</div>
                ) : (
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={trendData}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                      <XAxis dataKey="label" stroke="#94a3b8" fontSize={11} tickLine={false} />
                      <YAxis stroke="#94a3b8" fontSize={11} tickLine={false} axisLine={false} allowDecimals={false} />
                      <Tooltip contentStyle={{ borderRadius: 8, border: "1px solid #e2e8f0", fontSize: 12 }} />
                      <Legend wrapperStyle={{ fontSize: 11 }} />
                      <Area type="monotone" dataKey="leads" name="Leads" stroke="#0369A1" fill="#BAE6FD" strokeWidth={2} />
                      <Area type="monotone" dataKey="calls" name="Calls" stroke="#0EA5E9" fill="#E0F2FE" strokeWidth={2} />
                    </AreaChart>
                  </ResponsiveContainer>
                )}
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 lg:grid-cols-12">
            <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm lg:col-span-4" data-testid="pipeline-funnel-panel">
              <PanelHeader title="Pipeline funnel" hint="Derived from Responses" />
              <div className="space-y-0.5">
                {(data.pipeline_funnel || []).map((row) => (
                  <MiniBar
                    key={row.stage}
                    label={`${row.stage} (${row.rate_from_prev}%)`}
                    count={row.count}
                    max={funnelMax}
                    onClick={() => goLeads({ stage: row.stage })}
                  />
                ))}
              </div>
            </div>

            <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm lg:col-span-4">
              <PanelHeader title="Source breakdown" />
              <div className="max-h-56 overflow-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-left text-[10px] uppercase text-slate-400">
                      <th className="pb-1 font-medium">Source</th>
                      <th className="pb-1 font-medium text-right">Leads</th>
                      <th className="pb-1 font-medium text-right">Conv%</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(data.source_breakdown || []).map((row) => (
                      <tr
                        key={row.source}
                        className="cursor-pointer border-t border-slate-100 hover:bg-sky-50/50"
                        onClick={() => goLeads({ source: row.source })}
                      >
                        <td className="py-1.5 text-slate-700">{row.source}</td>
                        <td className="py-1.5 text-right tabular text-slate-600">{row.leads}</td>
                        <td className="py-1.5 text-right tabular text-slate-600">{row.conversion_rate}%</td>
                      </tr>
                    ))}
                    {(data.source_breakdown || []).length === 0 && (
                      <tr><td colSpan={3} className="py-6 text-center text-slate-400">No data</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm lg:col-span-4">
              <PanelHeader title="Aging / SLA" />
              <div className="space-y-0.5">
                {(data.aging_sla || []).map((row) => (
                  <MiniBar key={row.bucket} label={row.bucket} count={row.count} max={agingMax} />
                ))}
              </div>
              <div className="mt-3 grid grid-cols-2 gap-2">
                <div className="rounded-md bg-slate-50 p-2">
                  <p className="text-[10px] uppercase text-slate-400">Deposits</p>
                  <p className="font-display text-sm font-semibold text-slate-800"><Money value={k.ledger_credit} /></p>
                </div>
                <div className="rounded-md bg-slate-50 p-2">
                  <p className="text-[10px] uppercase text-slate-400">Net</p>
                  <p className="font-display text-sm font-semibold text-slate-800"><Money value={k.net_balance} /></p>
                </div>
              </div>
            </div>
          </div>

          {!isOwnScope && (
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-12">
              <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm lg:col-span-7">
                <PanelHeader title="Agent leaderboard" hint="By conversions" />
                <div className="h-52">
                  {(data.agent_performance || []).length === 0 ? (
                    <div className="flex h-full items-center justify-center text-sm text-slate-400">No agents in range</div>
                  ) : (
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={(data.agent_performance || []).slice(0, 8)}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                        <XAxis dataKey="name" stroke="#94a3b8" fontSize={10} tickLine={false} interval={0} angle={-20} textAnchor="end" height={50} />
                        <YAxis stroke="#94a3b8" fontSize={11} tickLine={false} axisLine={false} allowDecimals={false} />
                        <Tooltip contentStyle={{ borderRadius: 8, border: "1px solid #e2e8f0", fontSize: 12 }} />
                        <Bar dataKey="conversions" name="Conversions" fill="#0EA5E9" radius={[4, 4, 0, 0]} />
                        <Bar dataKey="calls" name="Calls" fill="#7DD3FC" radius={[4, 4, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  )}
                </div>
              </div>
              <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm lg:col-span-5">
                <PanelHeader title="Agent detail" />
                <div className="max-h-56 overflow-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-left text-[10px] uppercase text-slate-400">
                        <th className="pb-1 font-medium">Agent</th>
                        <th className="pb-1 font-medium text-right">Leads</th>
                        <th className="pb-1 font-medium text-right">Calls</th>
                        <th className="pb-1 font-medium text-right">Conv%</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(data.agent_performance || []).map((row) => (
                        <tr key={row.agent_id} className="border-t border-slate-100">
                          <td className="py-1.5 text-slate-700">{row.name}</td>
                          <td className="py-1.5 text-right tabular">{row.leads}</td>
                          <td className="py-1.5 text-right tabular">{row.calls}</td>
                          <td className="py-1.5 text-right tabular">{row.conversion_rate}%</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          <div className="flex flex-wrap gap-2">
            {(data.status_breakdown || []).map((s) => (
              <button
                key={s.status}
                type="button"
                onClick={() => goLeads({ status: s.status })}
                className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs shadow-sm hover:border-sky-300"
              >
                <span className="capitalize text-slate-600">{s.status}</span>
                <span className="ml-2 font-semibold tabular text-slate-900">{s.count}</span>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
