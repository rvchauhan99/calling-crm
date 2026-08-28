import { useEffect, useState, useCallback, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import api, { API, getToken, formatApiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { PageHeader, EmptyState, TableSkeleton, StatusPill } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";
import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription,
} from "@/components/ui/sheet";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { toast } from "sonner";
import { Upload, Plus, Search, Users, Wand2, UserCheck } from "lucide-react";

export default function Leads() {
  const { can } = useAuth();
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState(null);
  const [selected, setSelected] = useState([]);
  const [agents, setAgents] = useState([]);
  const [detail, setDetail] = useState(null);
  const [showCreate, setShowCreate] = useState(false);
  const [showAssign, setShowAssign] = useState(false);
  const [assignAgent, setAssignAgent] = useState("");
  const [form, setForm] = useState({ name: "", phone: "", email: "", source: "Manual", city: "" });
  const fileRef = useRef();

  const search = params.get("search") || "";
  const status = params.get("status") || "";
  const page = Number(params.get("page") || 1);

  const setParam = (k, v) => {
    const p = new URLSearchParams(params);
    if (v) p.set(k, v); else p.delete(k);
    if (k !== "page") p.set("page", "1");
    setParams(p);
  };

  const load = useCallback(async () => {
    const p = new URLSearchParams();
    if (search) p.set("search", search);
    if (status) p.set("status", status);
    p.set("page", page); p.set("page_size", 25);
    const { data } = await api.get(`/leads?${p.toString()}`);
    setData(data); setSelected([]);
  }, [search, status, page]);

  useEffect(() => { load().catch(() => {}); }, [load]);
  useEffect(() => {
    if (can("leads:assign")) api.get("/leads/assignable-callers").then((r) => setAgents(r.data.users)).catch(() => {});
  }, [can]);

  const createLead = async () => {
    try {
      await api.post("/leads", form);
      toast.success("Lead created");
      setShowCreate(false);
      setForm({ name: "", phone: "", email: "", source: "Manual", city: "" });
      load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const doImport = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    try {
      const res = await fetch(`${API}/leads/import`, {
        method: "POST", body: fd,
        headers: { Authorization: `Bearer ${getToken()}` },
      });
      const d = await res.json();
      if (!res.ok) throw new Error(formatApiError(d.detail));
      toast.success(`Imported ${d.created} · ${d.duplicates} dupes · ${d.invalid} invalid`);
      load();
    } catch (err) { toast.error(err.message); }
    fileRef.current.value = "";
  };

  const autoAssign = async () => {
    try {
      const { data } = await api.post("/leads/auto-assign");
      toast.success(`Auto-assigned ${data.assigned} leads by quota`);
      load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const doAssign = async () => {
    try {
      await api.post("/leads/assign", { lead_ids: selected, agent_id: assignAgent });
      toast.success("Leads assigned");
      setShowAssign(false); setAssignAgent("");
      load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const openDetail = async (id) => {
    const { data } = await api.get(`/leads/${id}`);
    setDetail(data);
  };

  const toggle = (id) => setSelected((s) => s.includes(id) ? s.filter((x) => x !== id) : [...s, id]);
  const totalPages = data ? Math.ceil(data.total / data.page_size) : 1;

  return (
    <div data-testid="leads-page">
      <PageHeader title="Leads" subtitle={data ? `${data.total} leads in scope` : ""}
        actions={
          <>
            {can("leads:assign") && (
              <Button variant="outline" onClick={autoAssign} data-testid="auto-assign-btn">
                <Wand2 size={16} className="mr-1.5" /> Auto-assign
              </Button>
            )}
            {can("leads:import") && (
              <>
                <input ref={fileRef} type="file" accept=".csv" hidden onChange={doImport} data-testid="import-input" />
                <Button variant="outline" onClick={() => fileRef.current.click()} data-testid="import-btn">
                  <Upload size={16} className="mr-1.5" /> Import CSV
                </Button>
              </>
            )}
            {can("leads:create") && (
              <Button className="bg-sky-500 hover:bg-sky-600" onClick={() => setShowCreate(true)} data-testid="new-lead-btn">
                <Plus size={16} className="mr-1.5" /> New Lead
              </Button>
            )}
          </>
        } />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[220px]">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <Input placeholder="Search name, phone, email…" defaultValue={search} data-testid="lead-search"
            onChange={(e) => setParam("search", e.target.value)} className="pl-9 focus-visible:ring-sky-500" />
        </div>
        <Select value={status || "all"} onValueChange={(v) => setParam("status", v === "all" ? "" : v)}>
          <SelectTrigger className="w-44" data-testid="status-filter"><SelectValue /></SelectTrigger>
          <SelectContent className="bg-white">
            <SelectItem value="all">All statuses</SelectItem>
            <SelectItem value="active">Active</SelectItem>
            <SelectItem value="inactive">Inactive</SelectItem>
            <SelectItem value="converted">Converted</SelectItem>
          </SelectContent>
        </Select>
        {selected.length > 0 && can("leads:assign") && (
          <Button variant="outline" onClick={() => setShowAssign(true)} data-testid="assign-selected-btn">
            <UserCheck size={16} className="mr-1.5" /> Assign ({selected.length})
          </Button>
        )}
      </div>

      <div className="rounded-lg border border-slate-200 bg-white shadow-sm">
        {!data ? <div className="p-4"><TableSkeleton /></div> :
          data.leads.length === 0 ? (
            <EmptyState icon={Users} title="No leads found" description="Import a CSV or create a lead to get started." testid="leads-empty" />
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
                    <TableCell onClick={() => openDetail(l.id)}>{l.disposition_name ? <StatusPill color={l.carry_forward ? "sky" : "amber"}>{l.disposition_name}</StatusPill> : <span className="text-slate-300">—</span>}</TableCell>
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

      {/* Create */}
      <Dialog open={showCreate} onOpenChange={setShowCreate}>
        <DialogContent className="bg-white" data-testid="create-lead-dialog">
          <DialogHeader><DialogTitle>New Lead</DialogTitle>
            <DialogDescription>Phone is normalized to E.164 (+91 default) and deduped.</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            {[["name", "Full name"], ["phone", "Phone"], ["email", "Email"], ["city", "City"], ["source", "Source"]].map(([k, label]) => (
              <div key={k}>
                <Label>{label}</Label>
                <Input value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })}
                  className="mt-1 focus-visible:ring-sky-500" data-testid={`lead-field-${k}`} />
              </div>
            ))}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowCreate(false)}>Cancel</Button>
            <Button className="bg-sky-500 hover:bg-sky-600" onClick={createLead} data-testid="save-lead-btn">Create</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Assign */}
      <Dialog open={showAssign} onOpenChange={setShowAssign}>
        <DialogContent className="bg-white" data-testid="assign-dialog">
          <DialogHeader><DialogTitle>Assign {selected.length} leads</DialogTitle></DialogHeader>
          <Select value={assignAgent} onValueChange={setAssignAgent}>
            <SelectTrigger data-testid="assign-agent-select"><SelectValue placeholder="Select caller" /></SelectTrigger>
            <SelectContent className="bg-white">
              {agents.map((a) => <SelectItem key={a.id} value={a.id}>{a.name}</SelectItem>)}
            </SelectContent>
          </Select>
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
  );
}
