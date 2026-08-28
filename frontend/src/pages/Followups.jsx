import { useEffect, useState, useCallback } from "react";
import api, { formatApiError } from "@/lib/api";
import { PageHeader, EmptyState, PageLoader, StatusPill } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { toast } from "sonner";
import { CalendarCheck, Check } from "lucide-react";

export default function Followups() {
  const [list, setList] = useState(null);

  const load = useCallback(async () => { const { data } = await api.get("/followups"); setList(data.followups); }, []);
  useEffect(() => { load().catch(() => {}); }, [load]);

  const reschedule = async (lid, val) => {
    try {
      await api.put(`/followups/${lid}`, { follow_up_at: val ? new Date(val).toISOString() : null });
      toast.success("Follow-up updated"); load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  const clear = async (lid) => { await api.put(`/followups/${lid}`, { follow_up_at: null }); toast.success("Cleared"); load(); };

  if (!list) return <PageLoader />;
  const now = new Date();

  return (
    <div data-testid="followups-page">
      <PageHeader title="Follow-ups" subtitle={`${list.length} scheduled callbacks`} />
      <div className="rounded-lg border border-slate-200 bg-white shadow-sm">
        {list.length === 0 ? (
          <EmptyState icon={CalendarCheck} title="No follow-ups scheduled" description="Callbacks scheduled during call logging appear here." testid="followups-empty" />
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="bg-slate-50">
                <TableHead>Lead</TableHead><TableHead>Phone</TableHead><TableHead>Disposition</TableHead>
                <TableHead>Scheduled</TableHead><TableHead>Reschedule</TableHead><TableHead></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {list.map((l) => {
                const due = new Date(l.follow_up_at) < now;
                return (
                  <TableRow key={l.id} data-testid={`followup-row-${l.id}`}>
                    <TableCell className="font-medium text-slate-800">{l.name}</TableCell>
                    <TableCell className="tabular text-slate-600">{l.phone}</TableCell>
                    <TableCell>{l.disposition_name ? <StatusPill>{l.disposition_name}</StatusPill> : "—"}</TableCell>
                    <TableCell><StatusPill color={due ? "red" : "sky"}>{new Date(l.follow_up_at).toLocaleString("en-IN")}</StatusPill></TableCell>
                    <TableCell>
                      <Input type="datetime-local" className="w-52 focus-visible:ring-sky-500"
                        onChange={(e) => reschedule(l.id, e.target.value)} data-testid={`reschedule-${l.id}`} />
                    </TableCell>
                    <TableCell><Button variant="ghost" size="sm" onClick={() => clear(l.id)} data-testid={`clear-followup-${l.id}`}><Check size={15} className="mr-1 text-sky-500" /> Done</Button></TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </div>
    </div>
  );
}
