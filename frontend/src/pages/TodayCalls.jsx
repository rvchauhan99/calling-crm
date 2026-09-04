import { useEffect, useState, useCallback } from "react";
import api, { formatApiError } from "@/lib/api";
import { PageHeader, EmptyState, PageLoader, StatusPill } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";
import { SearchableSelect } from "@/components/ui/searchable-select"
import { toast } from "sonner";
import { PhoneCall, PhoneOutgoing, AlertTriangle, CheckCircle2 } from "lucide-react";

const STAGES = ["New", "Contacted", "Qualified", "Proposal", "Won", "Lost"];

export default function TodayCalls() {
  const [data, setData] = useState(null);
  const [dispositions, setDispositions] = useState([]);
  const [active, setActive] = useState(null);
  const [form, setForm] = useState({ disposition_id: "", notes: "", follow_up_at: "", pipeline_stage: "", duration: 0 });

  const load = useCallback(async () => {
    const [tc, ds] = await Promise.all([api.get("/today-calls"), api.get("/dispositions")]);
    setData(tc.data);
    setDispositions(ds.data.dispositions.filter((d) => d.active));
  }, []);
  useEffect(() => { load().catch(() => {}); }, [load]);

  const openLog = (lead) => {
    setActive(lead);
    setForm({ disposition_id: "", notes: "", follow_up_at: "", pipeline_stage: lead.pipeline_stage || "New", duration: 0 });
  };

  const submit = async () => {
    if (!form.disposition_id) { toast.error("Select a disposition"); return; }
    try {
      const payload = { lead_id: active.id, ...form, duration: Number(form.duration) || 0,
        follow_up_at: form.follow_up_at ? new Date(form.follow_up_at).toISOString() : null };
      const { data: res } = await api.post("/calls/log", payload);
      toast.success(res.acw ? "Logged — after-call work pending" : "Call logged");
      setActive(null);
      load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const completeAcw = async () => {
    await api.post("/calls/complete-acw");
    toast.success("After-call work completed");
    load();
  };

  if (!data) return <PageLoader />;
  const acwId = data.acw_pending_lead_id;

  return (
    <div data-testid="today-calls-page">
      <PageHeader title="Today Calls" subtitle={`${data.leads.length} leads assigned for ${data.date}`}
        actions={acwId && <Button variant="outline" onClick={completeAcw} data-testid="complete-acw-btn"><CheckCircle2 size={16} className="mr-1.5" /> Complete ACW</Button>} />

      {acwId && (
        <div className="mb-4 flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800" data-testid="acw-banner">
          <AlertTriangle size={18} /> After-call work is pending. Resolve it before dispositioning a different lead.
        </div>
      )}

      {data.leads.length === 0 ? (
        <EmptyState icon={PhoneOutgoing} title="No calls for today" description="You have no leads assigned for today. Assigned leads will appear here." testid="today-empty" />
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {data.leads.map((l) => {
            const locked = acwId && acwId !== l.id;
            return (
              <div key={l.id} className={`rounded-lg border bg-white p-4 shadow-sm transition-shadow duration-200 hover:shadow-md ${acwId === l.id ? "border-amber-300 ring-1 ring-amber-200" : "border-slate-200"}`} data-testid={`today-card-${l.id}`}>
                <div className="flex items-start justify-between">
                  <div>
                    <p className="font-display font-semibold text-slate-800">{l.name}</p>
                    <p className="tabular text-sm text-slate-500">{l.phone}</p>
                  </div>
                  {l.disposition_name && <StatusPill color={l.carry_forward ? "sky" : "amber"}>{l.disposition_name}</StatusPill>}
                </div>
                <div className="mt-2 flex items-center gap-2 text-xs text-slate-400">
                  <span>{l.source}</span><span>·</span><span>{l.pipeline_stage}</span>
                  {l.follow_up_at && <><span>·</span><span className="text-sky-600">Follow-up {new Date(l.follow_up_at).toLocaleDateString("en-IN")}</span></>}
                </div>
                <Button className="mt-3 w-full bg-sky-500 hover:bg-sky-600" disabled={locked}
                  onClick={() => openLog(l)} data-testid={`log-call-btn-${l.id}`}>
                  <PhoneCall size={15} className="mr-1.5" /> {locked ? "ACW pending elsewhere" : "Log Call"}
                </Button>
              </div>
            );
          })}
        </div>
      )}

      <Dialog open={!!active} onOpenChange={(o) => !o && setActive(null)}>
        <DialogContent className="bg-white" data-testid="log-call-dialog">
          <DialogHeader>
            <DialogTitle>Log Call — {active?.name}</DialogTitle>
            <DialogDescription>{active?.phone}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <SearchableSelect
              value={form.disposition_id}
              onChange={(v) => setForm({ ...form, disposition_id: v })}
              options={dispositions.map((d) => ({
                value: d.id,
                label: d.name,
                color: d.color,
                requires_acw: d.requires_acw,
              }))}
              placeholder="Choose outcome"
              searchPlaceholder="Search dispositions…"
              label="Disposition"
              testId="disposition-select"
              renderItem={(o) => (
                <span className="flex items-center gap-2">
                  <span className="h-2.5 w-2.5 rounded-full shrink-0" style={{ background: o.color }} />
                  {o.label}
                  {o.requires_acw && <span className="text-[10px] text-amber-600">ACW</span>}
                </span>
              )}
            />
            <div className="grid grid-cols-2 gap-3">
              <SearchableSelect
                value={form.pipeline_stage}
                onChange={(v) => setForm({ ...form, pipeline_stage: v })}
                options={STAGES.map((s) => ({ value: s, label: s }))}
                placeholder="Select stage"
                searchPlaceholder="Search stages…"
                label="Pipeline stage"
                testId="stage-select"
              />
              <div>
                <Label>Duration (sec)</Label>
                <Input type="number" value={form.duration} className="mt-1 focus-visible:ring-sky-500"
                  onChange={(e) => setForm({ ...form, duration: e.target.value })} data-testid="duration-input" />
              </div>
            </div>
            <div>
              <Label>Follow-up date/time</Label>
              <Input type="datetime-local" value={form.follow_up_at} className="mt-1 focus-visible:ring-sky-500"
                onChange={(e) => setForm({ ...form, follow_up_at: e.target.value })} data-testid="followup-input" />
            </div>
            <div>
              <Label>Notes</Label>
              <Textarea value={form.notes} className="mt-1 focus-visible:ring-sky-500" rows={3}
                onChange={(e) => setForm({ ...form, notes: e.target.value })} data-testid="notes-input" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setActive(null)}>Cancel</Button>
            <Button className="bg-sky-500 hover:bg-sky-600" onClick={submit} data-testid="submit-call-btn">Save Disposition</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
