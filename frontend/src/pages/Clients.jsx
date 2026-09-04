import { useEffect, useState, useCallback } from "react"
import { useSearchParams } from "react-router-dom"
import api, { formatApiError } from "@/lib/api"
import { useAuth } from "@/context/AuthContext"
import { PageHeader, EmptyState, TableSkeleton, StatusPill, Money } from "@/components/common"
import { Lead360Sheet } from "@/components/leads/Lead360Sheet"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription,
} from "@/components/ui/sheet"
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog"
import { SearchableSelect } from "@/components/ui/searchable-select"
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table"
import { toast } from "sonner"
import { UserCog, Search, Plus, UserPlus } from "lucide-react"

export default function Clients() {
  const { can } = useAuth()
  const [params, setParams] = useSearchParams()
  const [data, setData] = useState(null)
  const [tabCounts, setTabCounts] = useState(null)
  const [detail, setDetail] = useState(null)
  const [note, setNote] = useState("")
  const [lead360Id, setLead360Id] = useState(null)
  const [showConvert, setShowConvert] = useState(false)
  const [convertible, setConvertible] = useState([])
  const [convertLeadId, setConvertLeadId] = useState("")
  const [convertSearch, setConvertSearch] = useState("")

  const search = params.get("search") || ""
  const page = Number(params.get("page") || 1)
  const statusTab = params.get("status") === "inactive" ? "inactive" : "active"

  const setParam = (k, v) => {
    const p = new URLSearchParams(params)
    if (v) p.set(k, v)
    else p.delete(k)
    if (k !== "page") p.set("page", "1")
    setParams(p)
  }

  const load = useCallback(async () => {
    const p = new URLSearchParams()
    if (search) p.set("search", search)
    p.set("status", statusTab)
    p.set("page", page)
    p.set("page_size", 25)
    const [{ data: list }, { data: counts }] = await Promise.all([
      api.get(`/clients?${p.toString()}`),
      api.get("/clients/tab-counts"),
    ])
    setData(list)
    setTabCounts(counts)
  }, [search, page, statusTab])

  useEffect(() => { load().catch(() => {}) }, [load])

  const open = async (id) => {
    const { data: d } = await api.get(`/clients/${id}`)
    setDetail(d)
  }

  const addNote = async () => {
    if (!note.trim()) return
    await api.post(`/clients/${detail.client.id}/notes`, { text: note })
    toast.success("Note added")
    setNote("")
    open(detail.client.id)
  }

  const loadConvertible = useCallback(async (q = "") => {
    const p = new URLSearchParams()
    if (q) p.set("search", q)
    p.set("page_size", 40)
    const { data: res } = await api.get(`/clients/convertible-leads?${p.toString()}`)
    setConvertible(res.leads || [])
  }, [])

  const handleOpenConvert = () => {
    setShowConvert(true)
    setConvertLeadId("")
    setConvertSearch("")
    loadConvertible().catch(() => {})
  }

  const handleConvert = async () => {
    if (!convertLeadId) {
      toast.error("Select a lead")
      return
    }
    try {
      await api.post("/clients/convert", { lead_id: convertLeadId })
      toast.success("Lead converted to client")
      setShowConvert(false)
      load()
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail))
    }
  }

  const totalPages = data ? Math.ceil(data.total / data.page_size) : 1

  return (
    <div data-testid="clients-page">
      <PageHeader
        title="Clients"
        subtitle={data ? `${data.total} ${statusTab} clients in scope` : ""}
        actions={can("clients:convert") && (
          <Button className="bg-sky-500 hover:bg-sky-600" onClick={handleOpenConvert} data-testid="convert-lead-btn">
            <UserPlus size={16} className="mr-1.5" /> Convert Lead
          </Button>
        )}
      />

      <Tabs
        value={statusTab}
        onValueChange={(v) => setParam("status", v === "active" ? "" : v)}
        className="mb-4"
      >
        <TabsList className="bg-slate-100">
          <TabsTrigger value="active" data-testid="tab-clients-active">
            Active{tabCounts ? ` (${tabCounts.active})` : ""}
          </TabsTrigger>
          <TabsTrigger value="inactive" data-testid="tab-clients-inactive">
            Inactive{tabCounts ? ` (${tabCounts.inactive})` : ""}
          </TabsTrigger>
        </TabsList>
      </Tabs>

      <div className="mb-4 relative max-w-md">
        <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
        <Input
          placeholder="Search name or phone…"
          defaultValue={search}
          data-testid="client-search"
          onChange={(e) => setParam("search", e.target.value)}
          className="pl-9 focus-visible:ring-sky-500"
        />
      </div>

      <div className="rounded-lg border border-slate-200 bg-white shadow-sm">
        {!data ? <div className="p-4"><TableSkeleton /></div> :
          data.clients.length === 0 ? (
            <EmptyState
              icon={UserCog}
              title="No clients yet"
              description="Convert a lead to a client to build their finance ledger."
              testid="clients-empty"
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="bg-slate-50">
                  <TableHead>Name</TableHead><TableHead>Phone</TableHead><TableHead>Owner</TableHead>
                  <TableHead>FTD</TableHead><TableHead>Balance</TableHead><TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.clients.map((c) => (
                  <TableRow
                    key={c.id}
                    className="cursor-pointer hover:bg-sky-50/50"
                    onClick={() => open(c.id)}
                    data-testid={`client-row-${c.id}`}
                  >
                    <TableCell className="font-medium text-slate-800">{c.name}</TableCell>
                    <TableCell className="tabular text-slate-600">{c.phone}</TableCell>
                    <TableCell className="text-slate-500">{c.assigned_name || "—"}</TableCell>
                    <TableCell>
                      {c.ftd_at
                        ? <StatusPill color="blue">FTD ✓</StatusPill>
                        : <StatusPill color="slate">No FTD</StatusPill>}
                    </TableCell>
                    <TableCell><Money value={c.balance} className="font-semibold text-slate-800" /></TableCell>
                    <TableCell><StatusPill color="sky">{c.status}</StatusPill></TableCell>
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

      <Sheet open={!!detail} onOpenChange={(o) => !o && setDetail(null)}>
        <SheetContent className="w-full overflow-y-auto bg-white sm:max-w-xl" data-testid="client-detail">
          {detail && (
            <>
              <SheetHeader>
                <SheetTitle className="font-display text-xl">{detail.client.name}</SheetTitle>
                <SheetDescription>{detail.client.phone} · {detail.client.email}</SheetDescription>
              </SheetHeader>
              {detail.client.lead_id && can("leads:view") && (
                <Button
                  variant="outline"
                  size="sm"
                  className="mt-3"
                  onClick={() => setLead360Id(detail.client.lead_id)}
                  data-testid="client-view-lead"
                >
                  View lead
                </Button>
              )}
              <div className="mt-5 grid grid-cols-3 gap-3">
                <div className="rounded-md bg-sky-50 p-3">
                  <p className="text-[11px] uppercase text-sky-500">Balance</p>
                  <p className="mt-1 font-display text-lg font-bold text-sky-700"><Money value={detail.client.balance} /></p>
                </div>
                <div className="rounded-md bg-slate-50 p-3">
                  <p className="text-[11px] uppercase text-slate-400">FTD</p>
                  <p className="mt-1 text-sm font-medium text-slate-700">
                    {detail.client.ftd_at ? new Date(detail.client.ftd_at).toLocaleDateString("en-IN") : "—"}
                  </p>
                </div>
                <div className="rounded-md bg-slate-50 p-3">
                  <p className="text-[11px] uppercase text-slate-400">Entries</p>
                  <p className="mt-1 text-sm font-medium text-slate-700">{detail.ledger.length}</p>
                </div>
              </div>

              <h4 className="mt-6 font-display text-sm font-semibold text-slate-800">Ledger</h4>
              <div className="mt-2 max-h-72 overflow-y-auto rounded-md border border-slate-200">
                <Table>
                  <TableHeader>
                    <TableRow className="bg-slate-50">
                      <TableHead>Date</TableHead><TableHead>Type</TableHead>
                      <TableHead className="text-right">Amount</TableHead>
                      <TableHead className="text-right">Balance</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {detail.ledger.map((e) => (
                      <TableRow key={e.id}>
                        <TableCell className="text-xs text-slate-500">{new Date(e.created_at).toLocaleDateString("en-IN")}</TableCell>
                        <TableCell>
                          <StatusPill color={e.type === "credit" ? "sky" : e.category === "reversal" ? "slate" : "amber"}>
                            {e.category}
                          </StatusPill>
                        </TableCell>
                        <TableCell className={`text-right tabular ${e.type === "credit" ? "text-sky-600" : "text-amber-600"}`}>
                          {e.type === "credit" ? "+" : "−"}<Money value={e.amount} />
                        </TableCell>
                        <TableCell className="text-right tabular text-slate-600"><Money value={e.balance_after} /></TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>

              {can("clients:edit") && (
                <>
                  <h4 className="mt-6 font-display text-sm font-semibold text-slate-800">Notes</h4>
                  <div className="mt-2 space-y-2">
                    {(detail.client.notes || []).map((n) => (
                      <div key={n.id} className="rounded-md bg-slate-50 p-2.5 text-sm">
                        <p className="text-slate-700">{n.text}</p>
                        <p className="mt-1 text-xs text-slate-400">{n.author} · {new Date(n.created_at).toLocaleString("en-IN")}</p>
                      </div>
                    ))}
                  </div>
                  <div className="mt-3 flex gap-2">
                    <Textarea
                      value={note}
                      onChange={(e) => setNote(e.target.value)}
                      rows={2}
                      placeholder="Add a note…"
                      className="focus-visible:ring-sky-500"
                      data-testid="client-note-input"
                    />
                    <Button className="bg-sky-500 hover:bg-sky-600" onClick={addNote} data-testid="add-note-btn">
                      <Plus size={16} />
                    </Button>
                  </div>
                </>
              )}
            </>
          )}
        </SheetContent>
      </Sheet>

      <Dialog open={showConvert} onOpenChange={setShowConvert}>
        <DialogContent className="bg-white" data-testid="convert-lead-dialog">
          <DialogHeader>
            <DialogTitle>Convert Lead to Client</DialogTitle>
            <DialogDescription>Select an active lead that is not already a client.</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label>Search</Label>
              <Input
                value={convertSearch}
                className="mt-1 focus-visible:ring-sky-500"
                placeholder="Name or phone…"
                data-testid="convert-lead-search"
                onChange={(e) => {
                  const v = e.target.value
                  setConvertSearch(v)
                  loadConvertible(v).catch(() => {})
                }}
              />
            </div>
            <SearchableSelect
              value={convertLeadId}
              onChange={setConvertLeadId}
              options={convertible.map((l) => ({
                value: l.id,
                label: `${l.name} · ${l.phone || "—"}`,
                keywords: [l.name, l.phone].filter(Boolean),
              }))}
              placeholder="Select lead"
              searchPlaceholder="Filter leads…"
              label="Lead"
              testId="convert-lead-select"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowConvert(false)}>Cancel</Button>
            <Button className="bg-sky-500 hover:bg-sky-600" onClick={handleConvert} data-testid="confirm-convert-btn">
              Convert
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Lead360Sheet leadId={lead360Id} onClose={() => setLead360Id(null)} />
    </div>
  )
}
