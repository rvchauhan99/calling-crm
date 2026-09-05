import { useState, useEffect, useMemo } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog"
import { SearchableSelect } from "@/components/ui/searchable-select"
import { LastRemarks } from "@/components/leads/LastRemarks"
import {
  nowDatetimeLocalValue,
  isCallBackDisposition,
  isConvertDisposition,
  isTerminalStage,
  parseDepositAmount,
} from "@/lib/followupBuckets"

const STAGES = ["New", "Contacted", "Qualified", "Proposal", "Won", "Lost"]

export const mappedStageForDisposition = (disp) => {
  if (!disp) return null
  if (disp.converts_to_client || disp.name === "Converted") return "Won"
  return disp.default_pipeline_stage || null
}

const emptyForm = (lead, stage, mode) => ({
  disposition_id: "",
  notes: "",
  // Do not copy old FU — logging clears unless a new next is entered.
  // Pipeline move into an active stage defaults to now (next action required).
  follow_up_at: mode === "move" && !isTerminalStage(stage) ? nowDatetimeLocalValue() : "",
  pipeline_stage: stage || lead?.pipeline_stage || "New",
  duration: 0,
  deposit_amount: "",
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
  const [form, setForm] = useState(emptyForm(null, "New", "log"))
  const selectedDisp = useMemo(
    () => dispositions.find((d) => d.id === form.disposition_id),
    [dispositions, form.disposition_id],
  )
  const mappedStage = mappedStageForDisposition(selectedDisp)
  const stageLocked = Boolean(mappedStage)
  const stage = mode === "move"
    ? targetStage
    : (mappedStage || form.pipeline_stage)
  const converts = isConvertDisposition(selectedDisp)
  const callBack = isCallBackDisposition(selectedDisp)
  const terminal = isTerminalStage(stage) || converts
  const fuDisabled = terminal
  const fuRequired = !fuDisabled && (
    callBack || (mode === "move" && !isTerminalStage(targetStage))
  )
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
      setForm(emptyForm(lead, targetStage || lead.pipeline_stage, mode))
    }
  }, [open, lead, targetStage, mode])

  const handleDispositionChange = (v) => {
    const disp = dispositions.find((d) => d.id === v)
    const mapped = mappedStageForDisposition(disp)
    const nextStage = mapped || (mode === "move" ? targetStage : form.pipeline_stage)
    let follow_up_at = form.follow_up_at
    if (isConvertDisposition(disp) || isTerminalStage(nextStage)) {
      follow_up_at = ""
    } else if (isCallBackDisposition(disp)) {
      follow_up_at = nowDatetimeLocalValue()
    } else if (mode === "move" && !isTerminalStage(nextStage) && !follow_up_at) {
      follow_up_at = nowDatetimeLocalValue()
    }
    setForm((prev) => ({
      ...prev,
      disposition_id: v,
      pipeline_stage: nextStage,
      follow_up_at,
    }))
  }

  const handleSubmit = () => {
    const nextFu = fuDisabled || !form.follow_up_at
      ? null
      : new Date(form.follow_up_at).toISOString()
    const deposit = converts ? parseDepositAmount(form.deposit_amount) : null
    onSubmit?.({
      ...form,
      pipeline_stage: stage,
      duration: Number(form.duration) || 0,
      follow_up_at: nextFu,
      deposit_amount: deposit,
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
                onChange={(v) => {
                  const next = {
                    ...form,
                    pipeline_stage: v,
                  }
                  if (isTerminalStage(v) || converts) next.follow_up_at = ""
                  setForm(next)
                }}
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
              Follow-up date/time{fuRequired ? " *" : fuDisabled ? "" : " (optional)"}
            </Label>
            <Input
              id="pipe-followup"
              type="datetime-local"
              value={form.follow_up_at}
              className="mt-1"
              onChange={(e) => setForm({ ...form, follow_up_at: e.target.value })}
              data-testid="pipeline-followup-input"
              required={fuRequired}
              disabled={fuDisabled}
            />
            {fuDisabled ? (
              <p className="mt-1 text-xs text-slate-500" data-testid="fu-disabled-hint">
                No follow-up after conversion / closed stage
              </p>
            ) : callBack ? (
              <p className="mt-1 text-xs text-slate-500" data-testid="fu-callback-hint">
                Scheduled for next follow-up (no ACW)
              </p>
            ) : (
              <p className="mt-1 text-xs text-slate-500" data-testid="fu-clear-hint">
                Leave blank to clear previous follow-up
              </p>
            )}
          </div>
          <div>
            <LastRemarks
              notes={lead?.last_notes}
              showLabel
              className="rounded-md border border-slate-100 bg-slate-50 p-2.5"
              testId="log-call-last-remarks"
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
          {converts && (
            <div data-testid="convert-deposit-section">
              <Label htmlFor="pipe-deposit">Deposit amount (₹)</Label>
              <Input
                id="pipe-deposit"
                type="number"
                min={0}
                step="0.01"
                value={form.deposit_amount}
                className="mt-1"
                placeholder="Optional"
                onChange={(e) => setForm({ ...form, deposit_amount: e.target.value })}
                data-testid="convert-deposit-amount"
                aria-label="Deposit amount"
              />
              <p className="mt-1 text-xs text-slate-500">Optional — posts to Finance Ledger</p>
            </div>
          )}
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
