import { useEffect, useState, useCallback, useMemo } from "react"
import { useSearchParams } from "react-router-dom"
import api, { API, getToken } from "@/lib/api"
import { useAuth } from "@/context/AuthContext"
import { PageHeader, EmptyState, TableSkeleton, StatusPill } from "@/components/common"
import { LeadPhoneLink } from "@/components/leads/LeadPhoneLink"
import { Lead360Sheet } from "@/components/leads/Lead360Sheet"
import { FilterToolbar, FilterField } from "@/components/filters/FilterToolbar"
import { useDebouncedParam } from "@/hooks/useDebouncedParam"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { SearchableSelect } from "@/components/ui/searchable-select"
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table"
import { History, Search, Download } from "lucide-react"
import { monthStartISO, todayISO } from "@/components/dashboard/atoms"

export default function CallHistory() {
  const { can, dataScope } = useAuth()
  const isOwnScope = dataScope === "OWN"
  const [params, setParams] = useSearchParams()
  const [data, setData] = useState(null)
  const [dispositions, setDispositions] = useState([])
  const [agents, setAgents] = useState([])
  const [lead360Id, setLead360Id] = useState(null)

  const search = params.get("search") || ""
  const disposition = params.get("disposition") || ""
  const agentId = params.get("agent_id") || ""
  const from = params.get("from") || ""
  const to = params.get("to") || ""
  const sort = params.get("sort") || "created_at_desc"
  const page = Number(params.get("page") || 1)

  const setParam = useCallback((k, v) => {
    const p = new URLSearchParams(params)
    if (v) p.set(k, v)
    else p.delete(k)
    if (k !== "page") p.set("page", "1")
    setParams(p)
  }, [params, setParams])

  const commitSearch = useCallback((v) => setParam("search", v.trim()), [setParam])
  const [searchLocal, setSearchLocal] = useDebouncedParam(search, commitSearch)

  const clearAll = () => {
    setParams(new URLSearchParams({ page: "1" }))
    setSearchLocal("")
  }

  const load = useCallback(async () => {
    const p = new URLSearchParams()
    if (search) p.set("search", search)
    if (disposition) p.set("disposition", disposition)
    if (!isOwnScope && agentId) p.set("agent_id", agentId)
    if (from) p.set("from", from)
    if (to) p.set("to", to)
    if (sort) p.set("sort", sort)
    p.set("page", page)
    p.set("page_size", 30)
    const { data: d } = await api.get(`/call-history?${p.toString()}`)
    setData(d)
  }, [search, disposition, agentId, from, to, sort, page, isOwnScope])

  useEffect(() => { load().catch(() => {}) }, [load])

  useEffect(() => {
    api.get("/dispositions").then((r) => setDispositions((r.data.dispositions || []).filter((d) => d.active))).catch(() => {})
    if (!isOwnScope) {
      api.get("/dashboard/filter-options").then((r) => setAgents(r.data.agents || [])).catch(() => {})
    }
  }, [isOwnScope])

  const exportCsv = async () => {
    const p = new URLSearchParams()
    if (search) p.set("search", search)
    if (disposition) p.set("disposition", disposition)
    if (!isOwnScope && agentId) p.set("agent_id", agentId)
    if (from) p.set("from", from)
    if (to) p.set("to", to)
    const res = await fetch(`${API}/call-history/export?${p.toString()}`, {
      headers: { Authorization: `Bearer ${getToken()}` },
    })
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = "call_history.csv"
    a.click()
  }

  const chips = useMemo(() => {
    const list = []
    if (search) list.push({ key: "search", label: `Search: ${search}`, onRemove: () => setParam("search", "") })
    if (disposition) list.push({ key: "disposition", label: `Disposition: ${disposition}`, onRemove: () => setParam("disposition", "") })
    if (!isOwnScope && agentId) {
      const name = agents.find((a) => a.id === agentId)?.name || agentId
      list.push({ key: "agent_id", label: `Agent: ${name}`, onRemove: () => setParam("agent_id", "") })
    }
    if (from || to) list.push({ key: "date", label: `${from || "…"} → ${to || "…"}`, onRemove: () => { setParam("from", ""); setParam("to", "") } })
    if (sort && sort !== "created_at_desc") {
      list.push({ key: "sort", label: "Sort: Oldest first", onRemove: () => setParam("sort", "") })
    }
    return list
  }, [search, disposition, agentId, from, to, sort, isOwnScope, agents, setParam])

  const totalPages = data ? Math.ceil(data.total / data.page_size) : 1

  return (
    <div data-testid="call-history-page">
      <PageHeader
        title="Call History"
        subtitle={data ? `${data.total} logged activities` : ""}
        actions={can("call_history:export") && (
          <Button variant="outline" onClick={exportCsv} data-testid="export-calls-btn">
            <Download size={16} className="mr-1.5" /> Export
          </Button>
        )}
      />

      <FilterToolbar
        testId="call-history-filters"
        search={(
          <>
            <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
            <Input
              placeholder="Search lead name or phone…"
              value={searchLocal}
              data-testid="call-search"
              onChange={(e) => setSearchLocal(e.target.value)}
              className="h-8 pl-8 focus-visible:ring-sky-500"
              aria-label="Search lead name or phone"
            />
          </>
        )}
        fields={(
          <>
            <FilterField label="From" className="w-36">
              <Input type="date" value={from} onChange={(e) => setParam("from", e.target.value)} className="h-8" data-testid="call-filter-from" />
            </FilterField>
            <FilterField label="To" className="w-36">
              <Input type="date" value={to} onChange={(e) => setParam("to", e.target.value)} className="h-8" data-testid="call-filter-to" />
            </FilterField>
            <FilterField label="Disposition" className="min-w-[10rem] w-44">
              <SearchableSelect
                value={disposition || "all"}
                onChange={(v) => setParam("disposition", v === "all" ? "" : v)}
                options={[
                  { value: "all", label: "All dispositions" },
                  ...dispositions.map((d) => ({ value: d.name, label: d.name })),
                ]}
                placeholder="All dispositions"
                testId="call-filter-disposition"
                className="h-8"
              />
            </FilterField>
            {!isOwnScope && (
              <FilterField label="Agent" className="w-40">
                <SearchableSelect
                  value={agentId || "all"}
                  onChange={(v) => setParam("agent_id", v === "all" ? "" : v)}
                  options={[
                    { value: "all", label: "All agents" },
                    ...agents.map((a) => ({ value: a.id, label: a.name })),
                  ]}
                  placeholder="All agents"
                  testId="call-filter-agent"
                  className="h-8"
                />
              </FilterField>
            )}
            <FilterField label="Sort" className="w-40">
              <SearchableSelect
                value={sort}
                onChange={(v) => setParam("sort", v === "created_at_desc" ? "" : v)}
                options={[
                  { value: "created_at_desc", label: "Newest first" },
                  { value: "created_at_asc", label: "Oldest first" },
                ]}
                placeholder="Sort"
                testId="call-filter-sort"
                className="h-8"
              />
            </FilterField>
            <FilterField label=" " className="w-auto">
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-8"
                onClick={() => {
                  setParam("from", monthStartISO())
                  setParam("to", todayISO())
                }}
                data-testid="call-preset-month"
              >
                This month
              </Button>
            </FilterField>
          </>
        )}
        chips={chips}
        onClearAll={chips.length ? clearAll : undefined}
      />

      <div className="rounded-lg border border-slate-200 bg-white shadow-sm">
        {!data ? <div className="p-4"><TableSkeleton /></div> :
          data.calls.length === 0 ? (
            <EmptyState icon={History} title="No call activity" description="Logged calls will appear here." testid="calls-empty" />
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="bg-slate-50">
                  <TableHead>When</TableHead><TableHead>Lead</TableHead><TableHead>Phone</TableHead>
                  <TableHead>Agent</TableHead><TableHead>Disposition</TableHead><TableHead>Duration</TableHead><TableHead>Notes</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.calls.map((c) => (
                  <TableRow key={c.id} data-testid={`call-row-${c.id}`}>
                    <TableCell className="whitespace-nowrap text-slate-500">{new Date(c.created_at).toLocaleString("en-IN")}</TableCell>
                    <TableCell>
                      <LeadPhoneLink leadId={c.lead_id} onOpen={setLead360Id} asName testId={`call-lead-name-${c.id}`}>
                        {c.lead_name}
                      </LeadPhoneLink>
                    </TableCell>
                    <TableCell>
                      <LeadPhoneLink leadId={c.lead_id} onOpen={setLead360Id} testId={`call-lead-phone-${c.id}`}>
                        {c.lead_phone}
                      </LeadPhoneLink>
                    </TableCell>
                    <TableCell className="text-slate-500">{c.agent_name}</TableCell>
                    <TableCell><StatusPill>{c.disposition_name}</StatusPill></TableCell>
                    <TableCell className="tabular text-slate-500">{c.duration}s</TableCell>
                    <TableCell className="max-w-[220px] truncate text-slate-500">{c.notes || "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
      </div>

      {data && totalPages > 1 && (
        <div className="mt-4 flex items-center justify-between text-sm text-slate-500">
          <span>Page {page} of {totalPages}</span>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setParam("page", String(page - 1))} data-testid="prev-page">Prev</Button>
            <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setParam("page", String(page + 1))} data-testid="next-page">Next</Button>
          </div>
        </div>
      )}

      <Lead360Sheet leadId={lead360Id} onClose={() => setLead360Id(null)} />
    </div>
  )
}
