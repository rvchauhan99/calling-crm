import { useEffect, useState, useCallback, useMemo } from "react"
import api, { formatApiError } from "@/lib/api"
import { PageHeader, EmptyState, PageLoader, StatusPill } from "@/components/common"
import { LeadPhoneLink } from "@/components/leads/LeadPhoneLink"
import { Lead360Sheet } from "@/components/leads/Lead360Sheet"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table"
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog"
import { SearchableSelect } from "@/components/ui/searchable-select"
import { toast } from "sonner"
import { CalendarCheck, PhoneCall, AlertTriangle, CheckCircle2 } from "lucide-react"
import { cn } from "@/lib/utils"
import {
  classifyFollowup,
  sortFollowups,
  followupPillColor,
  toDatetimeLocalValue,
} from "@/lib/followupBuckets"

export { classifyFollowup, sortFollowups } from "@/lib/followupBuckets"

const STAGES = ["New", "Contacted", "Qualified", "Proposal", "Won", "Lost"]
const FILTERS = [
  { id: "all", label: "All" },
  { id: "overdue", label: "Overdue" },
  { id: "today", label: "Due today" },
  { id: "upcoming", label: "Upcoming" },
]

export default function Followups() {
  const [list, setList] = useState(null)
  const [dispositions, setDispositions] = useState([])
  const [acwId, setAcwId] = useState(null)
  const [filter, setFilter] = useState("all")
  const [active, setActive] = useState(null)
  const [lead360Id, setLead360Id] = useState(null)
  const [form, setForm] = useState({
    disposition_id: "", notes: "", follow_up_at: "", pipeline_stage: "", duration: 0,
  })

  const load = useCallback(async () => {
    const [fu, ds, tc] = await Promise.all([
      api.get("/followups"),
      api.get("/dispositions"),
      api.get("/today-calls"),
    ])
    setList(fu.data.followups || [])
    setDispositions((ds.data.dispositions || []).filter((d) => d.active))
    setAcwId(tc.data.acw_pending_lead_id || null)
  }, [])

  useEffect(() => { load().catch(() => {}) }, [load])

  const handleFilterClick = (id) => setFilter(id)

  const openLog = (lead) => {
    setActive(lead)
    setForm({
      disposition_id: "",
      notes: "",
      follow_up_at: toDatetimeLocalValue(lead.follow_up_at),
      pipeline_stage: lead.pipeline_stage || "New",
      duration: 0,
    })
  }

  const handleSubmit = async () => {
    if (!form.disposition_id) {
      toast.error("Select a disposition")
      return
    }
    try {
      const payload = {
        lead_id: active.id,
        disposition_id: form.disposition_id,
        notes: form.notes,
        duration: Number(form.duration) || 0,
        pipeline_stage: form.pipeline_stage,
        follow_up_at: form.follow_up_at ? new Date(form.follow_up_at).toISOString() : null,
      }
      const { data: res } = await api.post("/calls/log", payload)
      if (res.converted) toast.success("Lead converted to client")
      else toast.success(res.acw ? "Logged — after-call work pending" : "Call logged")
      setActive(null)
      load()
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail))
    }
  }

  const handleCompleteAcw = async () => {
    await api.post("/calls/complete-acw")
    toast.success("After-call work completed")
    load()
  }

  const visible = useMemo(() => {
    if (!list) return []
    const now = new Date()
    const sorted = sortFollowups(list, now)
    if (filter === "all") return sorted
    return sorted.filter((l) => classifyFollowup(l.follow_up_at, now) === filter)
  }, [list, filter])

  if (!list) return <PageLoader />

  return (
    <div data-testid="followups-page">
      <PageHeader
        title="Follow-ups"
        subtitle={`${visible.length} scheduled callbacks`}
        actions={acwId && (
          <Button variant="outline" onClick={handleCompleteAcw} data-testid="complete-acw-btn">
            <CheckCircle2 size={16} className="mr-1.5" /> Complete ACW
          </Button>
        )}
      />

      {acwId && (
        <div
          className="mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800"
          data-testid="acw-banner"
        >
          <AlertTriangle size={18} /> After-call work pending — complete anytime. Calling other leads is not blocked.
          <Button size="sm" variant="outline" className="ml-auto shrink-0" onClick={handleCompleteAcw} data-testid="complete-acw-banner-btn">
            Complete ACW
          </Button>
        </div>
      )}

      <div className="mb-4 flex flex-wrap gap-2" data-testid="followups-filters" role="group" aria-label="Follow-up filters">
        {FILTERS.map((f) => (
          <Button
            key={f.id}
            type="button"
            variant={filter === f.id ? "default" : "outline"}
            size="sm"
            className={cn(filter === f.id && "bg-sky-500 hover:bg-sky-600 text-white")}
            onClick={() => handleFilterClick(f.id)}
            data-testid={`followups-filter-${f.id}`}
            aria-pressed={filter === f.id}
          >
            {f.label}
          </Button>
        ))}
      </div>

      <div className="rounded-lg border border-slate-200 bg-white shadow-sm">
        {visible.length === 0 ? (
          <EmptyState
            icon={CalendarCheck}
            title="No follow-ups scheduled"
            description="Callbacks scheduled during call logging appear here."
            testid="followups-empty"
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="bg-slate-50">
                <TableHead>Lead</TableHead>
                <TableHead>Phone</TableHead>
                <TableHead>Disposition</TableHead>
                <TableHead>Scheduled</TableHead>
                <TableHead></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible.map((l) => {
                const category = classifyFollowup(l.follow_up_at, new Date())
                return (
                  <TableRow
                    key={l.id}
                    data-testid={`followup-row-${l.id}`}
                    data-category={category}
                  >
                    <TableCell>
                      <LeadPhoneLink leadId={l.id} onOpen={setLead360Id} asName testId={`followup-name-${l.id}`}>
                        {l.name}
                      </LeadPhoneLink>
                    </TableCell>
                    <TableCell>
                      <LeadPhoneLink leadId={l.id} onOpen={setLead360Id} testId={`followup-phone-${l.id}`}>
                        {l.phone}
                      </LeadPhoneLink>
                    </TableCell>
                    <TableCell>
                      {l.disposition_name ? <StatusPill>{l.disposition_name}</StatusPill> : "—"}
                    </TableCell>
                    <TableCell>
                      <StatusPill color={followupPillColor(category)}>
                        {new Date(l.follow_up_at).toLocaleString("en-IN")}
                      </StatusPill>
                    </TableCell>
                    <TableCell>
                      <Button
                        className="bg-sky-500 hover:bg-sky-600 text-white"
                        size="sm"
                        onClick={() => openLog(l)}
                        data-testid={`log-call-btn-${l.id}`}
                        aria-label={`Log call for ${l.name}`}
                      >
                        <PhoneCall size={15} className="mr-1.5" />
                        Log Call
                      </Button>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        )}
      </div>

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
                <Label htmlFor="followups-duration">Duration (sec)</Label>
                <Input
                  id="followups-duration"
                  type="number"
                  value={form.duration}
                  className="mt-1 focus-visible:ring-sky-500"
                  onChange={(e) => setForm({ ...form, duration: e.target.value })}
                  data-testid="duration-input"
                />
              </div>
            </div>
            <div>
              <Label htmlFor="followups-followup">Follow-up date/time</Label>
              <Input
                id="followups-followup"
                type="datetime-local"
                value={form.follow_up_at}
                className="mt-1 focus-visible:ring-sky-500"
                onChange={(e) => setForm({ ...form, follow_up_at: e.target.value })}
                data-testid="followup-input"
              />
            </div>
            <div>
              <Label htmlFor="followups-remarks">Remarks</Label>
              <Textarea
                id="followups-remarks"
                value={form.notes}
                className="mt-1 focus-visible:ring-sky-500"
                rows={3}
                onChange={(e) => setForm({ ...form, notes: e.target.value })}
                data-testid="remarks-input"
                aria-label="Remarks"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setActive(null)}>Cancel</Button>
            <Button
              className="bg-sky-500 hover:bg-sky-600"
              onClick={handleSubmit}
              data-testid="submit-call-btn"
            >
              Save Disposition
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Lead360Sheet leadId={lead360Id} onClose={() => setLead360Id(null)} onLogged={() => load()} />
    </div>
  )
}
