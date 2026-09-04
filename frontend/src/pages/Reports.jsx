import { useCallback, useEffect, useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import api, { API, getToken } from "@/lib/api"
import { useAuth } from "@/context/AuthContext"
import { PageHeader, PageLoader, StatusPill, Money } from "@/components/common"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table"
import { SearchableSelect } from "@/components/ui/searchable-select"
import {
  PanelHeader, KpiCard, FilterChip,
  monthStartISO, todayISO, startOfWeekISO, monthsAgoISO, buildLeadHref,
} from "@/components/dashboard/atoms"
import {
  BarChart, Bar, PieChart, Pie, Cell, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from "recharts"
import { Download } from "lucide-react"

const PIE = ["#0EA5E9", "#0369A1", "#38BDF8", "#7DD3FC", "#F59E0B", "#EF4444", "#94A3B8", "#0284C7"]

const PRESETS = [
  { id: "today", label: "Today", apply: () => ({ from: todayISO(), to: todayISO() }) },
  { id: "week", label: "This Week", apply: () => ({ from: startOfWeekISO(), to: todayISO() }) },
  { id: "month", label: "This Month", apply: () => ({ from: monthStartISO(), to: todayISO() }) },
  { id: "3m", label: "Last 3M", apply: () => ({ from: monthsAgoISO(3), to: todayISO() }) },
]

const INITIAL_FILTERS = {
  from: monthStartISO(),
  to: todayISO(),
  assigned_to: "",
  source: "",
}

export default function Reports() {
  const { can, user } = useAuth()
  const navigate = useNavigate()
  const isAffiliate = user?.user_type === "affiliate"
  const defaultTab = isAffiliate ? "affiliate" : "caller"

  const [tab, setTab] = useState(defaultTab)
  const [filters, setFilters] = useState(INITIAL_FILTERS)
  const [activePreset, setActivePreset] = useState("month")
  const [agents, setAgents] = useState([])
  const [sources, setSources] = useState([])
  const [payload, setPayload] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async (kind, f) => {
    setLoading(true)
    try {
      const p = new URLSearchParams()
      if (f.from) p.set("from", f.from)
      if (f.to) p.set("to", f.to)
      if (kind === "caller" && f.assigned_to) p.set("assigned_to", f.assigned_to)
      if (kind === "company" && f.source) p.set("source", f.source)
      const { data } = await api.get(`/reports/${kind}?${p.toString()}`)
      setPayload(data)
    } catch {
      setPayload({ rows: [], summary: {} })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!isAffiliate) {
      api.get("/dashboard/filter-options").then((r) => {
        setAgents(r.data.agents || [])
        setSources(r.data.sources || [])
      }).catch(() => {})
    }
  }, [isAffiliate])

  useEffect(() => {
    load(tab, filters).catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab])

  const handlePreset = (preset) => {
    const next = { ...filters, ...preset.apply() }
    setFilters(next)
    setActivePreset(preset.id)
    load(tab, next)
  }

  const handleApply = () => {
    setActivePreset("")
    load(tab, filters)
  }

  const handleReset = () => {
    setFilters(INITIAL_FILTERS)
    setActivePreset("month")
    load(tab, INITIAL_FILTERS)
  }

  const handleTabChange = (nextTab) => {
    setTab(nextTab)
  }

  const exportCsv = async () => {
    const p = new URLSearchParams({ kind: tab })
    if (filters.from) p.set("from", filters.from)
    if (filters.to) p.set("to", filters.to)
    if (tab === "caller" && filters.assigned_to) p.set("assigned_to", filters.assigned_to)
    if (tab === "company" && filters.source) p.set("source", filters.source)
    const res = await fetch(`${API}/reports/export?${p.toString()}`, {
      headers: { Authorization: `Bearer ${getToken()}` },
    })
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `${tab}_report.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  const chips = useMemo(() => {
    const list = []
    if (filters.from || filters.to) {
      list.push({ key: "date", label: `${filters.from || "…"} → ${filters.to || "…"}` })
    }
    if (tab === "caller" && filters.assigned_to) {
      const name = agents.find((a) => a.id === filters.assigned_to)?.name || filters.assigned_to
      list.push({ key: "assigned_to", label: `Agent: ${name}` })
    }
    if (tab === "company" && filters.source) {
      list.push({ key: "source", label: `Source: ${filters.source}` })
    }
    return list
  }, [filters, tab, agents])

  const removeChip = (key) => {
    let next = { ...filters }
    if (key === "date") {
      next = { ...next, from: monthStartISO(), to: todayISO() }
      setActivePreset("month")
    } else {
      next = { ...next, [key]: "" }
    }
    setFilters(next)
    load(tab, next)
  }

  const rows = payload?.rows || []
  const summary = payload?.summary || {}
  const rangeLabel = filters.from && filters.to
    ? `${filters.from} → ${filters.to}`
    : "All time"

  return (
    <div data-testid="reports-page" className="space-y-3">
      <PageHeader
        title="Reports"
        subtitle={`Comparative analytics · IST · ${rangeLabel}`}
        actions={
          <div className="flex flex-wrap items-center gap-1.5">
            {PRESETS.map((p) => (
              <Button
                key={p.id}
                size="sm"
                variant={activePreset === p.id ? "default" : "outline"}
                className={activePreset === p.id ? "h-8 bg-sky-500 hover:bg-sky-600" : "h-8"}
                onClick={() => handlePreset(p)}
                data-testid={`preset-${p.id}`}
              >
                {p.label}
              </Button>
            ))}
            <Button size="sm" variant="outline" className="h-8" onClick={handleReset} data-testid="reports-reset">
              Reset
            </Button>
            <Button size="sm" className="h-8 bg-sky-500 hover:bg-sky-600" onClick={handleApply} data-testid="reports-apply">
              Apply
            </Button>
            {can("reports:export") && (
              <Button variant="outline" size="sm" className="h-8" onClick={exportCsv} data-testid="export-report-btn">
                <Download size={16} className="mr-1.5" /> Export {tab}
              </Button>
            )}
          </div>
        }
      />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <div>
          <Label className="text-[10px] uppercase text-slate-500">From</Label>
          <Input
            type="date"
            value={filters.from}
            onChange={(e) => setFilters((f) => ({ ...f, from: e.target.value }))}
            className="mt-1 h-9"
            data-testid="filter-from"
          />
        </div>
        <div>
          <Label className="text-[10px] uppercase text-slate-500">To</Label>
          <Input
            type="date"
            value={filters.to}
            onChange={(e) => setFilters((f) => ({ ...f, to: e.target.value }))}
            className="mt-1 h-9"
            data-testid="filter-to"
          />
        </div>
        {tab === "caller" && !isAffiliate && (
          <SearchableSelect
            label="Agent"
            value={filters.assigned_to || "all"}
            onChange={(v) => setFilters((f) => ({ ...f, assigned_to: v === "all" ? "" : v }))}
            options={[
              { value: "all", label: "All agents" },
              ...agents.map((a) => ({ value: a.id, label: a.name })),
            ]}
            placeholder="All agents"
            testId="filter-agent"
          />
        )}
        {tab === "company" && !isAffiliate && (
          <SearchableSelect
            label="Source"
            value={filters.source || "all"}
            onChange={(v) => setFilters((f) => ({ ...f, source: v === "all" ? "" : v }))}
            options={[
              { value: "all", label: "All sources" },
              ...sources.map((s) => ({ value: s, label: s })),
            ]}
            placeholder="All sources"
            testId="filter-source"
          />
        )}
      </div>

      {chips.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5" data-testid="filter-chips">
          {chips.map((c) => (
            <FilterChip key={c.key} label={c.label} onRemove={() => removeChip(c.key)} />
          ))}
          <button type="button" className="text-xs text-sky-600 hover:underline" onClick={handleReset}>
            Clear all
          </button>
        </div>
      )}

      <Tabs value={tab} onValueChange={handleTabChange}>
        <TabsList className="bg-slate-100" data-testid="reports-tabs">
          {!isAffiliate && <TabsTrigger value="caller" data-testid="tab-caller">Caller</TabsTrigger>}
          <TabsTrigger value="affiliate" data-testid="tab-affiliate">Affiliate</TabsTrigger>
          {!isAffiliate && <TabsTrigger value="company" data-testid="tab-company">Company</TabsTrigger>}
        </TabsList>

        {loading && !payload ? (
          <div className="mt-4"><PageLoader /></div>
        ) : (
          <>
            <TabsContent value="caller" className="mt-3 space-y-3">
              <div className="grid grid-cols-2 gap-2 md:grid-cols-4" data-testid="caller-kpis">
                <KpiCard testId="kpi-calls" label="Calls" value={summary.total_calls ?? 0} hint={`${summary.total_connected ?? 0} connected`} />
                <KpiCard testId="kpi-connect" label="Connect rate" value={`${summary.connect_rate ?? 0}%`} accent="blue" />
                <KpiCard testId="kpi-leads" label="Leads" value={summary.total_leads ?? 0} />
                <KpiCard testId="kpi-conv" label="Conversion" value={`${summary.conversion_rate ?? 0}%`} hint={`${summary.total_conversions ?? 0} converted`} accent="amber" />
              </div>
              <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
                <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
                  <PanelHeader title="Calls vs conversions" />
                  <div className="h-56">
                    {rows.length === 0 ? (
                      <EmptyChart />
                    ) : (
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={rows.slice(0, 10)}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                          <XAxis dataKey="name" stroke="#94a3b8" fontSize={10} tickLine={false} interval={0} angle={-20} textAnchor="end" height={48} />
                          <YAxis stroke="#94a3b8" fontSize={11} tickLine={false} axisLine={false} allowDecimals={false} />
                          <Tooltip contentStyle={{ borderRadius: 8, border: "1px solid #e2e8f0", fontSize: 12 }} />
                          <Legend wrapperStyle={{ fontSize: 11 }} />
                          <Bar dataKey="calls" name="Calls" fill="#0EA5E9" radius={[4, 4, 0, 0]} />
                          <Bar dataKey="conversions" name="Conversions" fill="#0369A1" radius={[4, 4, 0, 0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    )}
                  </div>
                </div>
                <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
                  <PanelHeader title="Connect rate by agent" />
                  <div className="h-56">
                    {rows.length === 0 ? (
                      <EmptyChart />
                    ) : (
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={[...rows].sort((a, b) => b.connect_rate - a.connect_rate).slice(0, 8)} layout="vertical">
                          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
                          <XAxis type="number" domain={[0, 100]} stroke="#94a3b8" fontSize={11} tickLine={false} />
                          <YAxis type="category" dataKey="name" width={80} stroke="#94a3b8" fontSize={10} tickLine={false} />
                          <Tooltip contentStyle={{ borderRadius: 8, border: "1px solid #e2e8f0", fontSize: 12 }} />
                          <Bar dataKey="connect_rate" name="Connect %" fill="#38BDF8" radius={[0, 4, 4, 0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    )}
                  </div>
                </div>
              </div>
              <ReportTable
                rows={rows}
                testid="caller-table"
                onRowClick={() => navigate("/leads?tab=assigned")}
                cols={[
                  ["name", "Caller"],
                  ["calls", "Calls"],
                  ["connected", "Connected"],
                  ["connect_rate", "Connect %"],
                  ["leads", "Leads"],
                  ["conversions", "Conversions"],
                  ["conversion_rate", "Conv %"],
                ]}
                rateKeys={["connect_rate", "conversion_rate"]}
              />
            </TabsContent>

            <TabsContent value="affiliate" className="mt-3 space-y-3">
              <div className="grid grid-cols-2 gap-2 md:grid-cols-4" data-testid="affiliate-kpis">
                <KpiCard testId="kpi-aff-clients" label="Clients" value={summary.total_clients ?? 0} />
                <KpiCard testId="kpi-aff-ftd" label="FTD" value={summary.total_ftd ?? 0} accent="amber" />
                <KpiCard testId="kpi-aff-ftd-rate" label="FTD rate" value={`${summary.ftd_rate ?? 0}%`} accent="blue" />
                <KpiCard testId="kpi-aff-balance" label="Total balance" value={<Money value={summary.total_balance ?? 0} />} />
              </div>
              <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
                <PanelHeader title="Clients vs FTD" />
                <div className="h-56">
                  {rows.length === 0 ? (
                    <EmptyChart />
                  ) : (
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={rows}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                        <XAxis dataKey="name" stroke="#94a3b8" fontSize={11} tickLine={false} />
                        <YAxis stroke="#94a3b8" fontSize={11} tickLine={false} axisLine={false} allowDecimals={false} />
                        <Tooltip contentStyle={{ borderRadius: 8, border: "1px solid #e2e8f0", fontSize: 12 }} />
                        <Legend wrapperStyle={{ fontSize: 11 }} />
                        <Bar dataKey="clients" name="Clients" fill="#0EA5E9" radius={[4, 4, 0, 0]} />
                        <Bar dataKey="ftd" name="FTD" fill="#F59E0B" radius={[4, 4, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  )}
                </div>
              </div>
              <ReportTable
                rows={rows}
                testid="affiliate-table"
                money={["total_balance"]}
                rateKeys={["ftd_rate"]}
                onRowClick={() => navigate("/clients")}
                cols={[
                  ["name", "Affiliate"],
                  ["clients", "Clients"],
                  ["ftd", "FTD"],
                  ["ftd_rate", "FTD %"],
                  ["total_balance", "Total Balance"],
                ]}
              />
            </TabsContent>

            <TabsContent value="company" className="mt-3 space-y-3">
              <div className="grid grid-cols-2 gap-2 md:grid-cols-3" data-testid="company-kpis">
                <KpiCard testId="kpi-co-leads" label="Leads" value={summary.total_leads ?? 0} />
                <KpiCard testId="kpi-co-conv" label="Conversions" value={summary.total_conversions ?? 0} accent="amber" />
                <KpiCard testId="kpi-co-rate" label="Conversion rate" value={`${summary.conversion_rate ?? 0}%`} accent="blue" />
              </div>
              <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
                <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
                  <PanelHeader title="Leads by source" />
                  <div className="h-56">
                    {rows.length === 0 ? (
                      <EmptyChart />
                    ) : (
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={rows}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                          <XAxis dataKey="source" stroke="#94a3b8" fontSize={10} tickLine={false} interval={0} angle={-20} textAnchor="end" height={48} />
                          <YAxis stroke="#94a3b8" fontSize={11} tickLine={false} axisLine={false} allowDecimals={false} />
                          <Tooltip contentStyle={{ borderRadius: 8, border: "1px solid #e2e8f0", fontSize: 12 }} />
                          <Bar dataKey="leads" name="Leads" fill="#0EA5E9" radius={[4, 4, 0, 0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    )}
                  </div>
                </div>
                <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
                  <PanelHeader title="Conversion mix" />
                  <div className="h-56">
                    {rows.length === 0 ? (
                      <EmptyChart />
                    ) : (
                      <ResponsiveContainer width="100%" height="100%">
                        <PieChart>
                          <Pie
                            data={rows.filter((r) => r.conversions > 0)}
                            dataKey="conversions"
                            nameKey="source"
                            innerRadius={40}
                            outerRadius={70}
                            paddingAngle={2}
                          >
                            {rows.map((_, i) => <Cell key={i} fill={PIE[i % PIE.length]} />)}
                          </Pie>
                          <Tooltip contentStyle={{ borderRadius: 8, border: "1px solid #e2e8f0", fontSize: 12 }} />
                        </PieChart>
                      </ResponsiveContainer>
                    )}
                  </div>
                </div>
              </div>
              <ReportTable
                rows={rows}
                testid="company-table"
                rateKeys={["conversion_rate"]}
                onRowClick={(row) => navigate(buildLeadHref({ source: row.source, tab: "assigned" }))}
                cols={[
                  ["source", "Source"],
                  ["leads", "Leads"],
                  ["conversions", "Conversions"],
                  ["conversion_rate", "Conv %"],
                ]}
              />
            </TabsContent>
          </>
        )}
      </Tabs>
    </div>
  )
}

function EmptyChart() {
  return <div className="flex h-full items-center justify-center text-sm text-slate-400">No data in range</div>
}

function ReportTable({ rows, cols, money = [], rateKeys = [], testid, onRowClick }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white shadow-sm" data-testid={testid}>
      <Table>
        <TableHeader>
          <TableRow className="bg-slate-50">
            {cols.map(([k, l]) => <TableHead key={k}>{l}</TableHead>)}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.length === 0 ? (
            <TableRow>
              <TableCell colSpan={cols.length} className="py-8 text-center text-slate-400">No data</TableCell>
            </TableRow>
          ) : rows.map((r, i) => (
            <TableRow
              key={i}
              className={onRowClick ? "cursor-pointer hover:bg-sky-50/50" : ""}
              onClick={() => onRowClick?.(r)}
            >
              {cols.map(([k]) => (
                <TableCell key={k} className={k === cols[0][0] ? "font-medium text-slate-800" : "tabular text-slate-600"}>
                  {money.includes(k) ? (
                    <Money value={r[k]} />
                  ) : rateKeys.includes(k) ? (
                    <StatusPill color="sky">{r[k]}%</StatusPill>
                  ) : (
                    r[k]
                  )}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
