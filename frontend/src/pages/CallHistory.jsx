import { useEffect, useState, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import api, { API, getToken } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { PageHeader, EmptyState, TableSkeleton, StatusPill } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { History, Search, Download } from "lucide-react";

export default function CallHistory() {
  const { can } = useAuth();
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState(null);
  const search = params.get("search") || "";
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
    p.set("page", page); p.set("page_size", 30);
    const { data } = await api.get(`/call-history?${p.toString()}`);
    setData(data);
  }, [search, page]);
  useEffect(() => { load().catch(() => {}); }, [load]);

  const exportCsv = async () => {
    const res = await fetch(`${API}/call-history/export`, { headers: { Authorization: `Bearer ${getToken()}` } });
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = "call_history.csv"; a.click();
  };

  const totalPages = data ? Math.ceil(data.total / data.page_size) : 1;

  return (
    <div data-testid="call-history-page">
      <PageHeader title="Call History" subtitle={data ? `${data.total} logged activities` : ""}
        actions={can("call_history:export") && <Button variant="outline" onClick={exportCsv} data-testid="export-calls-btn"><Download size={16} className="mr-1.5" /> Export</Button>} />

      <div className="mb-4 relative max-w-md">
        <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
        <Input placeholder="Search lead name or phone…" defaultValue={search} data-testid="call-search"
          onChange={(e) => setParam("search", e.target.value)} className="pl-9 focus-visible:ring-sky-500" />
      </div>

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
                    <TableCell className="font-medium text-slate-800">{c.lead_name}</TableCell>
                    <TableCell className="tabular text-slate-600">{c.lead_phone}</TableCell>
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
    </div>
  );
}
