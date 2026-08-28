import { useEffect, useState, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import api from "@/lib/api";
import { PageHeader, EmptyState, TableSkeleton, StatusPill } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { FileSearch, Search } from "lucide-react";

const ACTION_COLORS = {
  login: "sky", create: "blue", update: "sky", delete: "red", deactivate: "red",
  ledger_post: "blue", ledger_reverse: "amber", export: "slate", import: "sky",
  assign: "sky", convert: "blue", log_call: "sky",
};

export default function Audit() {
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
    p.set("page", page); p.set("page_size", 40);
    try { const { data } = await api.get(`/audit?${p.toString()}`); setData(data); }
    catch { setData({ logs: [], total: 0, page_size: 40 }); }
  }, [search, page]);
  useEffect(() => { load(); }, [load]);

  const totalPages = data ? Math.ceil(data.total / data.page_size) : 1;

  return (
    <div data-testid="audit-page">
      <PageHeader title="Audit Log" subtitle={data ? `${data.total} events` : ""} />
      <div className="mb-4 relative max-w-md">
        <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
        <Input placeholder="Search action, entity or actor…" defaultValue={search} data-testid="audit-search"
          onChange={(e) => setParam("search", e.target.value)} className="pl-9 focus-visible:ring-sky-500" />
      </div>

      <div className="rounded-lg border border-slate-200 bg-white shadow-sm">
        {!data ? <div className="p-4"><TableSkeleton /></div> :
          data.logs.length === 0 ? (
            <EmptyState icon={FileSearch} title="No audit events" description="Logins, exports, role changes and ledger edits are recorded here." testid="audit-empty" />
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="bg-slate-50">
                  <TableHead>When</TableHead><TableHead>Actor</TableHead><TableHead>Action</TableHead>
                  <TableHead>Entity</TableHead><TableHead>Details</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.logs.map((l) => (
                  <TableRow key={l.id} data-testid={`audit-row-${l.id}`}>
                    <TableCell className="whitespace-nowrap text-xs text-slate-500">{new Date(l.created_at).toLocaleString("en-IN")}</TableCell>
                    <TableCell className="font-medium text-slate-700">{l.actor_name}</TableCell>
                    <TableCell><StatusPill color={ACTION_COLORS[l.action] || "slate"}>{l.action}</StatusPill></TableCell>
                    <TableCell className="text-slate-500">{l.entity}</TableCell>
                    <TableCell className="max-w-[280px] truncate text-xs text-slate-400">{Object.keys(l.meta || {}).length ? JSON.stringify(l.meta) : "—"}</TableCell>
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
