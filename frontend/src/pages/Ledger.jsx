import { useEffect, useState, useCallback } from "react";
import api, { API, getToken, formatApiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { PageHeader, EmptyState, TableSkeleton, StatusPill, Money, StatCard } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { toast } from "sonner";
import { Wallet, Plus, Download, Undo2, ArrowUpRight, ArrowDownRight } from "lucide-react";

function uuid() {
  return (crypto.randomUUID && crypto.randomUUID()) || `${Date.now()}-${Math.random()}`;
}

export default function Ledger() {
  const { can } = useAuth();
  const [data, setData] = useState(null);
  const [clients, setClients] = useState([]);
  const [page, setPage] = useState(1);
  const [show, setShow] = useState(false);
  const [form, setForm] = useState({ client_id: "", type: "credit", amount: "", category: "deposit", description: "" });

  const load = useCallback(async () => {
    const { data } = await api.get(`/ledger?page=${page}&page_size=40`);
    setData(data);
  }, [page]);
  useEffect(() => { load().catch(() => {}); }, [load]);
  useEffect(() => {
    if (can("ledger:post")) api.get("/clients?page_size=500").then((r) => setClients(r.data.clients));
  }, [can]);

  const post = async () => {
    if (!form.client_id || !form.amount) { toast.error("Client and amount required"); return; }
    try {
      await api.post("/ledger/post", {
        client_id: form.client_id, type: form.type, amount: Number(form.amount),
        category: form.category, description: form.description, idempotency_key: uuid(),
      });
      toast.success("Entry posted");
      setShow(false);
      setForm({ client_id: "", type: "credit", amount: "", category: "deposit", description: "" });
      load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const reverse = async (id) => {
    if (!window.confirm("Post a reversing entry? The original stays immutable.")) return;
    try { await api.post(`/ledger/${id}/reverse`); toast.success("Reversed"); load(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const exportCsv = async () => {
    const res = await fetch(`${API}/ledger/export`, { headers: { Authorization: `Bearer ${getToken()}` } });
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = "ledger.csv"; a.click();
  };

  const totalPages = data ? Math.ceil(data.total / data.page_size) : 1;

  return (
    <div data-testid="ledger-page">
      <PageHeader title="Finance Ledger" subtitle="Append-only · immutable entries · idempotent posts"
        actions={
          <>
            {can("ledger:export") && <Button variant="outline" onClick={exportCsv} data-testid="export-ledger-btn"><Download size={16} className="mr-1.5" /> Export</Button>}
            {can("ledger:post") && <Button className="bg-sky-500 hover:bg-sky-600" onClick={() => setShow(true)} data-testid="new-entry-btn"><Plus size={16} className="mr-1.5" /> Post Entry</Button>}
          </>
        } />

      {data && (
        <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-3">
          <StatCard testid="ledger-credit" label="Total Deposits" value={<Money value={data.totals.credit} />} icon={ArrowUpRight} />
          <StatCard testid="ledger-debit" label="Total Withdrawals" value={<Money value={data.totals.debit} />} icon={ArrowDownRight} accent="amber" />
          <StatCard testid="ledger-net" label="Net Position" value={<Money value={(data.totals.credit - data.totals.debit)} />} icon={Wallet} accent="blue" />
        </div>
      )}

      <div className="rounded-lg border border-slate-200 bg-white shadow-sm">
        {!data ? <div className="p-4"><TableSkeleton /></div> :
          data.entries.length === 0 ? (
            <EmptyState icon={Wallet} title="No ledger entries" description="Posted transactions appear here." testid="ledger-empty" />
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="bg-slate-50">
                  <TableHead>Date</TableHead><TableHead>Client</TableHead><TableHead>Category</TableHead><TableHead>Description</TableHead>
                  <TableHead className="text-right">Amount</TableHead><TableHead className="text-right">Balance After</TableHead>
                  <TableHead>By</TableHead>{can("ledger:reverse") && <TableHead></TableHead>}
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.entries.map((e) => (
                  <TableRow key={e.id} data-testid={`ledger-row-${e.id}`}>
                    <TableCell className="whitespace-nowrap text-xs text-slate-500">{new Date(e.created_at).toLocaleString("en-IN")}</TableCell>
                    <TableCell className="font-medium text-slate-800">{e.client_name}</TableCell>
                    <TableCell><StatusPill color={e.type === "credit" ? "sky" : e.category === "reversal" ? "slate" : "amber"}>{e.category}</StatusPill></TableCell>
                    <TableCell className="max-w-[220px] truncate text-slate-500">{e.description || "—"}</TableCell>
                    <TableCell className={`text-right tabular font-medium ${e.type === "credit" ? "text-sky-600" : "text-amber-600"}`}>{e.type === "credit" ? "+" : "−"}<Money value={e.amount} /></TableCell>
                    <TableCell className="text-right tabular text-slate-600"><Money value={e.balance_after} /></TableCell>
                    <TableCell className="text-slate-500">{e.created_by_name}</TableCell>
                    {can("ledger:reverse") && (
                      <TableCell>
                        {!e.reversal_of && <Button variant="ghost" size="sm" onClick={() => reverse(e.id)} data-testid={`reverse-${e.id}`}><Undo2 size={15} className="text-slate-500" /></Button>}
                      </TableCell>
                    )}
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
            <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)} data-testid="prev-page">Prev</Button>
            <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setPage(page + 1)} data-testid="next-page">Next</Button>
          </div>
        </div>
      )}

      <Dialog open={show} onOpenChange={setShow}>
        <DialogContent className="bg-white" data-testid="ledger-dialog">
          <DialogHeader><DialogTitle>Post Ledger Entry</DialogTitle>
            <DialogDescription>Entries are immutable; corrections use reversals.</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label>Client</Label>
              <Select value={form.client_id} onValueChange={(v) => setForm({ ...form, client_id: v })}>
                <SelectTrigger className="mt-1" data-testid="ledger-client"><SelectValue placeholder="Select client" /></SelectTrigger>
                <SelectContent className="bg-white max-h-64">
                  {clients.map((c) => <SelectItem key={c.id} value={c.id}>{c.name} — ₹{Number(c.balance).toLocaleString("en-IN")}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Type</Label>
                <Select value={form.type} onValueChange={(v) => setForm({ ...form, type: v, category: v === "credit" ? "deposit" : "withdrawal" })}>
                  <SelectTrigger className="mt-1" data-testid="ledger-type"><SelectValue /></SelectTrigger>
                  <SelectContent className="bg-white">
                    <SelectItem value="credit">Credit (deposit)</SelectItem>
                    <SelectItem value="debit">Debit (withdrawal)</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div><Label>Amount (₹)</Label><Input type="number" value={form.amount} className="mt-1 focus-visible:ring-sky-500" onChange={(e) => setForm({ ...form, amount: e.target.value })} data-testid="ledger-amount" /></div>
            </div>
            <div><Label>Description</Label><Input value={form.description} className="mt-1 focus-visible:ring-sky-500" onChange={(e) => setForm({ ...form, description: e.target.value })} data-testid="ledger-desc" /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShow(false)}>Cancel</Button>
            <Button className="bg-sky-500 hover:bg-sky-600" onClick={post} data-testid="post-entry-btn">Post</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
