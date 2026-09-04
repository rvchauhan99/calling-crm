import { useState, useEffect, useMemo } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog"
import { SearchableSelect } from "@/components/ui/searchable-select"
import { toDatetimeLocalValue } from "@/lib/followupBuckets"

const STAGES = ["New", "Contacted", "Qualified", "Proposal", "Won", "Lost"]

export const mappedStageForDisposition = (disp) => {
  if (!disp) return null
  if (disp.converts_to_client || disp.name === "Converted") return "Won"
  return disp.default_pipeline_stage || null
}

const emptyForm = (lead, stage) => ({
  disposition_id: "",
  notes: "",
  follow_up_at: toDatetimeLocalValue(lead?.follow_up_at) || "",
  pipeline_stage: stage || lead?.pipeline_stage || "New",
  duration: 0,
})

/** Shared Log Call / move-stage dialog used by Pipeline drop + detail. */
export const PipelineLogCallDialog = ({
  open,
  lead,
  targetStage,
  dispositions = [],
  mode = "log",
  onClose,
  onSubmit,
}) => {
  const [form, setForm] = useState(emptyForm(null, "New"))
  const selectedDisp = useMemo(
    () => dispositions.find((d) => d.id === form.disposition_id),
    [dispositions, form.disposition_id],
  )
  const mappedStage = mappedStageForDisposition(selectedDisp)
  const stageLocked = Boolean(mappedStage)
  const stage = mode === "move"
    ? targetStage
    : (mappedStage || form.pipeline_stage)
  const fuRequired = stage !== "Won" && stage !== "Lost"
  const title = mode === "move"
    ? `Move to ${targetStage}`
    : `Log Call — ${lead?.name || ""}`

  const visibleDispositions = useMemo(() => {
    if (mode !== "move" || !targetStage) return dispositions
    return dispositions.filter((d) => {
      const mapped = mappedStageForDisposition(d)
      return !mapped || mapped === targetStage
    })
  }, [dispositions, mode, targetStage])

  useEffect(() => {
    if (open && lead) {
      setForm(emptyForm(lead, targetStage || lead.pipeline_stage))
    }
  }, [open, lead, targetStage])

  const handleDispositionChange = (v) => {
    const disp = dispositions.find((d) => d.id === v)
    const mapped = mappedStageForDisposition(disp)
    setForm((prev) => ({
      ...prev,
      disposition_id: v,
      pipeline_stage: mapped || (mode === "move" ? targetStage : prev.pipeline_stage),
    }))
  }

  const handleSubmit = () => {
    onSubmit?.({
      ...form,
      pipeline_stage: stage,
      duration: Number(form.duration) || 0,
      follow_up_at: form.follow_up_at ? new Date(form.follow_up_at).toISOString() : null,
    })
  }

  if (!lead) return null

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose?.()}>
      <DialogContent className="bg-white" data-testid="pipeline-log-call-dialog">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            {lead.phone}
            {mode === "move" && " · Disposition and follow-up required to complete the move"}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          {mode === "move" && (
            <div className="rounded-md bg-slate-50 px-3 py-2 text-sm">
              <span className="text-slate-500">Target stage: </span>
              <span className="font-semibold text-slate-800" data-testid="move-target-stage">{targetStage}</span>
              <p className="mt-1 text-xs text-slate-500">
                Only responses that map to this stage (or have no mapping) are listed
              </p>
            </div>
          )}
          <SearchableSelect
            value={form.disposition_id}
            onChange={handleDispositionChange}
            options={visibleDispositions.map((d) => ({
              value: d.id,
              label: d.name,
              color: d.color,
              requires_acw: d.requires_acw,
            }))}
            placeholder="Choose disposition"
            label="Disposition"
            testId="pipeline-disposition-select"
            renderItem={(o) => (
              <span className="flex items-center gap-2">
                <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: o.color }} />
                {o.label}
                {o.requires_acw && <span className="text-[10px] text-amber-600">ACW</span>}
              </span>
            )}
          />
          {mode === "log" && (
            <div className="grid grid-cols-2 gap-3">
              <SearchableSelect
                value={stage}
                onChange={(v) => setForm({ ...form, pipeline_stage: v })}
                options={STAGES.map((s) => ({ value: s, label: s }))}
                placeholder="Stage"
                label="Pipeline stage"
                testId="pipeline-stage-select"
                disabled={stageLocked}
              />
              <div>
                <Label htmlFor="pipe-duration">Duration (sec)</Label>
                <Input
                  id="pipe-duration"
                  type="number"
                  value={form.duration}
                  className="mt-1"
                  onChange={(e) => setForm({ ...form, duration: e.target.value })}
                  data-testid="pipeline-duration-input"
                />
              </div>
              {stageLocked && (
                <p className="col-span-2 text-xs text-slate-500" data-testid="stage-locked-hint">
                  Stage locked by response mapping ({mappedStage})
                </p>
              )}
            </div>
          )}
          {mode === "move" && (
            <div>
              <Label htmlFor="pipe-duration-move">Duration (sec)</Label>
              <Input
                id="pipe-duration-move"
                type="number"
                value={form.duration}
                className="mt-1"
                onChange={(e) => setForm({ ...form, duration: e.target.value })}
                data-testid="pipeline-duration-input"
              />
            </div>
          )}
          <div>
            <Label htmlFor="pipe-followup">
              Follow-up date/time{fuRequired ? " *" : " (optional)"}
            </Label>
            <Input
              id="pipe-followup"
              type="datetime-local"
              value={form.follow_up_at}
              className="mt-1"
              onChange={(e) => setForm({ ...form, follow_up_at: e.target.value })}
              data-testid="pipeline-followup-input"
              required={fuRequired}
            />
          </div>
          <div>
            <Label htmlFor="pipe-remarks">Remarks</Label>
            <Textarea
              id="pipe-remarks"
              value={form.notes}
              className="mt-1"
              rows={3}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
              data-testid="pipeline-remarks-input"
              aria-label="Remarks"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} data-testid="pipeline-log-cancel">Cancel</Button>
          <Button className="bg-sky-500 hover:bg-sky-600" onClick={handleSubmit} data-testid="pipeline-log-submit">
            {mode === "move" ? "Confirm move" : "Save Disposition"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export const PIPELINE_STAGES = STAGES
