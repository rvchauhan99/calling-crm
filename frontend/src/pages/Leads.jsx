import { useEffect, useState, useCallback, useRef } from "react"
import { useSearchParams } from "react-router-dom"
import api, { API, getToken, formatApiError } from "@/lib/api"
import { useAuth } from "@/context/AuthContext"
import { PageHeader, EmptyState, TableSkeleton, StatusPill } from "@/components/common"
import { AutoAssignDialog } from "@/components/leads/AutoAssignDialog"
import { PhoneField } from "@/components/leads/PhoneField"
import { EmailField } from "@/components/leads/EmailField"
import { SourceSelect } from "@/components/leads/SourceSelect"
import { validateLeadForm } from "@/lib/leadValidation"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog"
import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription,
} from "@/components/ui/sheet"
import { SearchableSelect } from "@/components/ui/searchable-select"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table"
import { toast } from "sonner"
import { Upload, Plus, Search, Users, Wand2, UserCheck, Download } from "lucide-react"

export default function Leads() {
  const { can, dataScope } = useAuth()
  const isOwnScope = dataScope === "OWN"
  const [params, setParams] = useSearchParams()
  const [data, setData] = useState(null)
  const [tabCounts, setTabCounts] = useState(null)
  const [filterOptions, setFilterOptions] = useState(null)
  const [selected, setSelected] = useState([])
  const [agents, setAgents] = useState([])
  const [detail, setDetail] = useState(null)
  const [showCreate, setShowCreate] = useState(false)
  const [showAssign, setShowAssign] = useState(false)
  const [showAutoAssign, setShowAutoAssign] = useState(false)
  const [assignAgent, setAssignAgent] = useState("")
  const [form, setForm] = useState({ name: "", phone: "", email: "", source: "Manual", city: "" })
  const [formErrors, setFormErrors] = useState({})
  const fileRef = useRef()

  const search = params.get("search") || ""
  const status = params.get("status") || ""
  const stage = params.get("stage") || ""
  const source = params.get("source") || ""
  const disposition = params.get("disposition") || ""
  const tabParam = params.get("tab")
  const tab = isOwnScope ? "assigned" : (tabParam || "unassigned")
  const page = Number(params.get("page") || 1)

  const setParam = (k, v) => {
    const p = new URLSearchParams(params)
    if (v) p.set(k, v)
    else p.delete(k)
    if (k !== "page") p.set("page", "1")
    setParams(p)
  }

  const setTab = (v) => {
    const p = new URLSearchParams(params)
    p.set("tab", v)
    p.set("page", "1")
    setParams(p)
  }

  useEffect(() => {
    if (isOwnScope && tabParam === "unassigned") {
      setTab("assigned")
    }
  }, [isOwnScope, tabParam])

  const loadCounts = useCallback(async () => {
    try {
      const { data: counts } = await api.get("/leads/tab-counts")
      setTabCounts(counts)
    } catch {
      setTabCounts(null)
    }
  }, [])

  const load = useCallback(async () => {
    const p = new URLSearchParams()
    if (search) p.set("search", search)
    if (status) p.set("status", status)
    if (stage) p.set("stage", stage)
    if (source) p.set("source", source)
    if (disposition) p.set("disposition", disposition)
    if (!isOwnScope) {
      p.set("assignment_status", tab === "assigned" ? "assigned" : "unassigned")
    }
    p.set("page", page)
    p.set("page_size", 25)
    const { data: listData } = await api.get(`/leads?${p.toString()}`)
    setData(listData)
    setSelected([])
    loadCounts()
  }, [search, status, stage, source, disposition, tab, page, loadCounts, isOwnScope])

  useEffect(() => { load().catch(() => {}) }, [load])

  useEffect(() => {
    api.get("/leads/filter-options").then((r) => setFilterOptions(r.data)).catch(() => {})
  }, [])

  useEffect(() => {
    if (can("leads:assign")) {
      api.get("/leads/assignable-callers").then((r) => setAgents(r.data.users)).catch(() => {})
    }
  }, [can])

  const createLead = async () => {
    const { fieldErrors, isValid } = validateLeadForm(form)
    setFormErrors(fieldErrors)
    if (!isValid) return
    try {
      await api.post("/leads", form)
      toast.success("Lead created")
      setShowCreate(false)
      setForm({ name: "", phone: "", email: "", source: "Manual", city: "" })
      setFormErrors({})
      setTab("unassigned")
      load()
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)) }
  }

  const handleOpenCreate = () => {
    setFormErrors({})
    setShowCreate(true)
  }

  const handleFormChange = (key, value) => {
    setForm((f) => ({ ...f, [key]: value }))
    if (formErrors[key]) {
      setFormErrors((errs) => {
        const next = { ...errs }
        delete next[key]
        return next
      })
    }
  }

  const doImport = async (e) => {
    const file = e.target.files[0]
    if (!file) return
    const fd = new FormData()
    fd.append("file", file)
    try {
      const res = await fetch(`${API}/leads/import`, {
        method: "POST", body: fd,
        headers: { Authorization: `Bearer ${getToken()}` },
      })
      const d = await res.json()
      if (!res.ok) throw new Error(formatApiError(d.detail))
      toast.success(`Imported ${d.created} · ${d.duplicates} dupes · ${d.invalid} invalid`)
      load()
    } catch (err) { toast.error(err.message) }
    fileRef.current.value = ""
  }

  const downloadTemplate = async () => {
    try {
      const res = await fetch(`${API}/leads/import/template`, {
        headers: { Authorization: `Bearer ${getToken()}` },
      })
      if (!res.ok) throw new Error("Failed to download template")
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = "leads_import_template.csv"
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      toast.error(err.message)
    }
  }

  const doAssign = async () => {
    try {
      await api.post("/leads/assign", { lead_ids: selected, agent_id: assignAgent })
      toast.success("Leads assigned")
      setShowAssign(false)
      setAssignAgent("")
      load()
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)) }
  }

  const openDetail = async (id) => {
    const { data: detailData } = await api.get(`/leads/${id}`)
    setDetail(detailData)
  }

  const toggle = (id) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]))
  const totalPages = data ? Math.ceil(data.total / data.page_size) : 1

  const tabLabel = isOwnScope ? "my" : tab === "assigned" ? "assigned" : "unassigned"
  const subtitle = data
    ? `${data.total} ${tabLabel} lead${data.total === 1 ? "" : "s"}`
    : ""

  const emptyDescription = isOwnScope
    ? "No leads assigned to you yet."
    : tab === "unassigned"
      ? "Import a CSV or create a lead to get started."
      : "No assigned leads match your filters."

  return (
    <div data-testid="leads-page">
      <PageHeader
        title="Leads"
        subtitle={subtitle}
        actions={
          <>
            {can("leads:assign") && (
              <Button variant="outline" onClick={() => setShowAutoAssign(true)} data-testid="auto-assign-btn">
                <Wand2 size={16} className="mr-1.5" /> Auto-assign
              </Button>
            )}
            {can("leads:import") && (
              <>
                <Button variant="outline" onClick={downloadTemplate} data-testid="download-template-btn">
                  <Download size={16} className="mr-1.5" /> Download Template
                </Button>
                <input ref={fileRef} type="file" accept=".csv" hidden onChange={doImport} data-testid="import-input" />
                <Button variant="outline" onClick={() => fileRef.current.click()} data-testid="import-btn">
                  <Upload size={16} className="mr-1.5" /> Import CSV
                </Button>
              </>
            )}
            {can("leads:create") && (
              <Button className="bg-sky-500 hover:bg-sky-600" onClick={handleOpenCreate} data-testid="new-lead-btn">
                <Plus size={16} className="mr-1.5" /> New Lead
              </Button>
            )}
          </>
        }
      />

      {!isOwnScope && (
        <Tabs value={tab} onValueChange={setTab} className="mb-4">
          <TabsList className="bg-slate-100">
            <TabsTrigger value="unassigned" data-testid="tab-unassigned">
              Unassigned{tabCounts ? ` (${tabCounts.unassigned})` : ""}
            </TabsTrigger>
            <TabsTrigger value="assigned" data-testid="tab-assigned">
              Assigned{tabCounts ? ` (${tabCounts.assigned})` : ""}
            </TabsTrigger>
          </TabsList>
        </Tabs>
      )}

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative min-w-[220px] flex-1">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <Input
            placeholder="Search name, phone, email…"
            defaultValue={search}
            data-testid="lead-search"
            onChange={(e) => setParam("search", e.target.value)}
            className="pl-9 focus-visible:ring-sky-500"
          />
        </div>
        <SearchableSelect
          value={status || "all"}
          onChange={(v) => setParam("status", v === "all" ? "" : v)}
          options={[
            { value: "all", label: "All statuses" },
            { value: "active", label: "Active" },
            { value: "inactive", label: "Inactive" },
            { value: "converted", label: "Converted" },
          ]}
          placeholder="All statuses"
          searchPlaceholder="Search status…"
          testId="status-filter"
          className="w-40"
        />
        <SearchableSelect
          value={stage || "all"}
          onChange={(v) => setParam("stage", v === "all" ? "" : v)}
          options={[
            { value: "all", label: "All stages" },
            ...(filterOptions?.stages || []).map((s) => ({ value: s, label: s })),
          ]}
          placeholder="All stages"
          searchPlaceholder="Search stages…"
          testId="stage-filter"
          className="w-40"
        />
        <SourceSelect
          value={source || "all"}
          onChange={(v) => setParam("source", v === "all" ? "" : v)}
          includeImport
          includeAll
          label=""
          placeholder="All sources"
          testId="source-filter"
          className="w-40"
        />
        <SearchableSelect
          value={disposition || "all"}
          onChange={(v) => setParam("disposition", v === "all" ? "" : v)}
          options={[
            { value: "all", label: "All dispositions" },
            { value: "__none__", label: "No disposition" },
            ...(filterOptions?.dispositions || []).map((d) => ({ value: d.name, label: d.name })),
          ]}
          placeholder="All dispositions"
          searchPlaceholder="Search dispositions…"
          testId="disposition-filter"
          className="w-44"
        />
        {selected.length > 0 && can("leads:assign") && (
          <Button variant="outline" onClick={() => setShowAssign(true)} data-testid="assign-selected-btn">
            <UserCheck size={16} className="mr-1.5" /> Assign ({selected.length})
          </Button>
        )}
      </div>

      <div className="rounded-lg border border-slate-200 bg-white shadow-sm">
        {!data ? <div className="p-4"><TableSkeleton /></div> :
          data.leads.length === 0 ? (
            <EmptyState icon={Users} title="No leads found" description={emptyDescription} testid="leads-empty" />
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="bg-slate-50">
                  {can("leads:assign") && <TableHead className="w-10"></TableHead>}
                  <TableHead>Name</TableHead>
                  <TableHead>Phone</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead>Disposition</TableHead>
                  <TableHead>Stage</TableHead>
                  <TableHead>Assigned</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.leads.map((l) => (
                  <TableRow key={l.id} className="cursor-pointer hover:bg-sky-50/50" data-testid={`lead-row-${l.id}`}>
                    {can("leads:assign") && (
                      <TableCell onClick={(e) => e.stopPropagation()}>
                        <Checkbox checked={selected.includes(l.id)} onCheckedChange={() => toggle(l.id)} data-testid={`lead-check-${l.id}`} />
                      </TableCell>
                    )}
                    <TableCell onClick={() => openDetail(l.id)} className="font-medium text-slate-800">{l.name}</TableCell>
                    <TableCell onClick={() => openDetail(l.id)} className="tabular text-slate-600">{l.phone}</TableCell>
                    <TableCell onClick={() => openDetail(l.id)} className="text-slate-500">{l.source}</TableCell>
                    <TableCell onClick={() => openDetail(l.id)}>
                      {l.disposition_name
                        ? <StatusPill color={l.carry_forward ? "sky" : "amber"}>{l.disposition_name}</StatusPill>
                        : <span className="text-slate-300">—</span>}
                    </TableCell>
                    <TableCell onClick={() => openDetail(l.id)} className="text-slate-600">{l.pipeline_stage}</TableCell>
                    <TableCell onClick={() => openDetail(l.id)} className="text-slate-500">{l.assigned_name || "—"}</TableCell>
                    <TableCell onClick={() => openDetail(l.id)}>
                      <StatusPill color={l.status === "converted" ? "blue" : l.status === "active" ? "sky" : "slate"}>{l.status}</StatusPill>
                    </TableCell>
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

      <AutoAssignDialog
        open={showAutoAssign}
        onOpenChange={setShowAutoAssign}
        onComplete={load}
      />

      {/* Create */}
      <Dialog open={showCreate} onOpenChange={(open) => { setShowCreate(open); if (!open) setFormErrors({}) }}>
        <DialogContent className="bg-white" data-testid="create-lead-dialog">
          <DialogHeader>
            <DialogTitle>New Lead</DialogTitle>
            <DialogDescription>New leads are added to the unassigned pool. Phone is normalized to E.164 (+91 default).</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label htmlFor="lead-name">Full name</Label>
              <Input
                id="lead-name"
                value={form.name}
                onChange={(e) => handleFormChange("name", e.target.value)}
                className={`mt-1 focus-visible:ring-sky-500 ${formErrors.name ? "border-red-400" : ""}`}
                data-testid="lead-field-name"
                aria-invalid={!!formErrors.name}
              />
              {formErrors.name && <p className="mt-1 text-xs text-red-600" role="alert">{formErrors.name}</p>}
            </div>
            <PhoneField
              value={form.phone}
              onChange={(v) => handleFormChange("phone", v)}
              error={formErrors.phone}
            />
            <EmailField
              value={form.email}
              onChange={(v) => handleFormChange("email", v)}
              error={formErrors.email}
            />
            <div>
              <Label htmlFor="lead-city">City</Label>
              <Input
                id="lead-city"
                value={form.city}
                onChange={(e) => handleFormChange("city", e.target.value)}
                className="mt-1 focus-visible:ring-sky-500"
                data-testid="lead-field-city"
              />
            </div>
            <SourceSelect
              value={form.source}
              onChange={(v) => handleFormChange("source", v)}
              testId="lead-field-source"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowCreate(false)}>Cancel</Button>
            <Button
              className="bg-sky-500 hover:bg-sky-600"
              onClick={createLead}
              disabled={!form.name.trim() || !form.phone.trim()}
              data-testid="save-lead-btn"
            >
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Assign / Reassign */}
      <Dialog open={showAssign} onOpenChange={setShowAssign}>
        <DialogContent className="bg-white" data-testid="assign-dialog">
          <DialogHeader>
            <DialogTitle>{tab === "assigned" ? "Reassign" : "Assign"} {selected.length} leads</DialogTitle>
          </DialogHeader>
          <SearchableSelect
            value={assignAgent}
            onChange={setAssignAgent}
            options={agents.map((a) => ({ value: a.id, label: a.name }))}
            placeholder="Select caller"
            searchPlaceholder="Search callers…"
            testId="assign-agent-select"
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowAssign(false)}>Cancel</Button>
            <Button className="bg-sky-500 hover:bg-sky-600" disabled={!assignAgent} onClick={doAssign} data-testid="confirm-assign-btn">Assign</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Lead 360 */}
      <Sheet open={!!detail} onOpenChange={(o) => !o && setDetail(null)}>
        <SheetContent className="w-full overflow-y-auto bg-white sm:max-w-lg" data-testid="lead-360">
          {detail && (
            <>
              <SheetHeader>
                <SheetTitle className="font-display text-xl">{detail.lead.name}</SheetTitle>
                <SheetDescription>{detail.lead.phone} · {detail.lead.email}</SheetDescription>
              </SheetHeader>
              <div className="mt-5 grid grid-cols-2 gap-3 text-sm">
                {[["Source", detail.lead.source], ["City", detail.lead.city || "—"], ["Stage", detail.lead.pipeline_stage],
                  ["Assigned", detail.lead.assigned_name || "—"], ["Disposition", detail.lead.disposition_name || "—"],
                  ["Status", detail.lead.status]].map(([k, v]) => (
                  <div key={k} className="rounded-md bg-slate-50 p-2.5">
                    <p className="text-[11px] uppercase tracking-wide text-slate-400">{k}</p>
                    <p className="mt-0.5 font-medium text-slate-700">{v}</p>
                  </div>
                ))}
              </div>
              {detail.client && (
                <div className="mt-4 rounded-md border border-sky-200 bg-sky-50 p-3 text-sm">
                  <p className="font-semibold text-sky-800">Converted to client</p>
                  <p className="text-sky-700">Balance: ₹{Number(detail.client.balance).toLocaleString("en-IN")}</p>
                </div>
              )}
              <h4 className="mt-6 font-display text-sm font-semibold text-slate-800">Call activity ({detail.calls.length})</h4>
              <div className="mt-2 space-y-2">
                {detail.calls.length === 0 && <p className="text-sm text-slate-400">No calls logged.</p>}
                {detail.calls.map((c) => (
                  <div key={c.id} className="rounded-md border border-slate-200 p-3 text-sm">
                    <div className="flex justify-between">
                      <StatusPill>{c.disposition_name}</StatusPill>
                      <span className="text-xs text-slate-400">{new Date(c.created_at).toLocaleString("en-IN")}</span>
                    </div>
                    {c.notes && <p className="mt-1.5 text-slate-600">{c.notes}</p>}
                    <p className="mt-1 text-xs text-slate-400">by {c.agent_name}</p>
                  </div>
                ))}
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </div>
  )
}
