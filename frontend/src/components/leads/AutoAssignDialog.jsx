import { useEffect, useState, useCallback, useMemo } from "react"
import api, { formatApiError } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog"
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table"
import { toast } from "sonner"

export function AutoAssignDialog({ open, onOpenChange, onComplete }) {
  const [maxLeads, setMaxLeads] = useState("")
  const [preview, setPreview] = useState(null)
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [counts, setCounts] = useState({})

  const syncCountsFromPreview = useCallback((data) => {
    const next = {}
    for (const a of data?.by_agent || []) {
      if (a.slots_available > 0 || a.assigned > 0) {
        next[a.agent_id] = a.assigned
      }
    }
    setCounts(next)
  }, [])

  const loadPreview = useCallback(async (count) => {
    setPreviewLoading(true)
    try {
      const p = new URLSearchParams()
      if (count) p.set("max_leads", count)
      const { data } = await api.get(`/leads/auto-assign/preview?${p.toString()}`)
      setPreview(data)
      syncCountsFromPreview(data)
    } catch (e) {
      setPreview(null)
      setCounts({})
      toast.error(formatApiError(e.response?.data?.detail))
    } finally {
      setPreviewLoading(false)
    }
  }, [syncCountsFromPreview])

  useEffect(() => {
    if (!open) {
      setMaxLeads("")
      setPreview(null)
      setResult(null)
      setCounts({})
      return
    }
    loadPreview("")
  }, [open, loadPreview])

  const handleMaxLeadsChange = (value) => {
    setMaxLeads(value)
    setResult(null)
    const parsed = value.trim() ? Number(value) : null
    if (value.trim() && (Number.isNaN(parsed) || parsed < 0)) return
    loadPreview(value.trim() ? String(parsed) : "")
  }

  const handleCountChange = (agentId, slotsAvailable, raw) => {
    setResult(null)
    if (raw.trim() === "") {
      setCounts((prev) => ({ ...prev, [agentId]: 0 }))
      return
    }
    const n = Number(raw)
    if (Number.isNaN(n) || n < 0) return
    const clamped = Math.min(Math.floor(n), slotsAvailable)
    setCounts((prev) => ({ ...prev, [agentId]: clamped }))
  }

  const agents = useMemo(() => {
    const source = result || preview
    return source?.by_agent?.filter((a) => a.assigned > 0 || a.slots_available > 0) || []
  }, [result, preview])

  const totalSelected = useMemo(() => {
    if (result) return result.assigned
    return agents.reduce((sum, a) => sum + (Number(counts[a.agent_id]) || 0), 0)
  }, [result, agents, counts])

  const requestedCap = preview
    ? (maxLeads.trim()
      ? Math.min(Number(maxLeads), preview.available_in_pool)
      : preview.assigned)
    : 0

  const showPoolNote = preview && maxLeads.trim()
    && Number(maxLeads) > preview.available_in_pool

  const showTotalMismatch = !result && preview && maxLeads.trim()
    && totalSelected !== requestedCap && totalSelected > 0

  const handleConfirm = async () => {
    setLoading(true)
    try {
      const body = {
        allocations: agents
          .map((a) => ({
            agent_id: a.agent_id,
            count: Number(counts[a.agent_id]) || 0,
          }))
          .filter((a) => a.count > 0),
      }
      if (maxLeads.trim()) body.max_leads = Number(maxLeads)
      const { data } = await api.post("/leads/auto-assign", body)
      setResult(data)
      toast.success(`Auto-assigned ${data.assigned} leads`)
      onComplete?.()
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail))
    } finally {
      setLoading(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto bg-white sm:max-w-2xl" data-testid="auto-assign-dialog">
        <DialogHeader>
          <DialogTitle>{result ? "Assignment complete" : "Auto-assign leads"}</DialogTitle>
          <DialogDescription>
            {result
              ? `${result.assigned} leads assigned from ${result.available_in_pool} available in pool.`
              : "Distribute unassigned leads equally among callers with remaining daily quota. Adjust per-agent counts before confirming."}
          </DialogDescription>
        </DialogHeader>

        {!result && (
          <div className="space-y-4">
            {preview && (
              <p className="text-sm text-slate-600">
                <span className="font-medium text-slate-800">{preview.available_in_pool}</span> unassigned leads available
              </p>
            )}
            <div>
              <Label htmlFor="max-leads">Leads to assign</Label>
              <Input
                id="max-leads"
                type="number"
                min="0"
                placeholder="All available up to agent quotas"
                value={maxLeads}
                onChange={(e) => handleMaxLeadsChange(e.target.value)}
                className="mt-1 focus-visible:ring-sky-500"
                data-testid="auto-assign-count"
              />
              {showPoolNote && (
                <p className="mt-1.5 text-xs text-amber-600">
                  Only {preview.available_in_pool} leads available — {preview.available_in_pool} will be assigned.
                </p>
              )}
              {showTotalMismatch && (
                <p className="mt-1.5 text-xs text-amber-600" data-testid="auto-assign-total-note">
                  Selected total is {totalSelected} (cap was {requestedCap}). Counts will be used as entered.
                </p>
              )}
            </div>
          </div>
        )}

        {(result || preview) && agents.length > 0 && (
          <div>
            <h4 className="mb-2 text-sm font-semibold text-slate-700">
              {result
                ? "Agent summary"
                : `Preview — ${totalSelected} lead${totalSelected === 1 ? "" : "s"} will be assigned`}
            </h4>
            <div className="rounded-md border border-slate-200">
              <Table>
                <TableHeader>
                  <TableRow className="bg-slate-50">
                    <TableHead>Agent</TableHead>
                    <TableHead className="text-right">Quota</TableHead>
                    <TableHead className="text-right">Today</TableHead>
                    <TableHead className="text-right">Slots</TableHead>
                    <TableHead className="text-right">{result ? "Assigned" : "Will assign"}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {agents.map((a) => (
                    <TableRow key={a.agent_id}>
                      <TableCell className="font-medium">{a.agent_name}</TableCell>
                      <TableCell className="text-right tabular-nums">{a.quota}</TableCell>
                      <TableCell className="text-right tabular-nums">{a.assigned_today_before}</TableCell>
                      <TableCell className="text-right tabular-nums">{a.slots_available}</TableCell>
                      <TableCell className="text-right">
                        {result ? (
                          <span className="tabular-nums font-medium text-sky-600">{a.assigned}</span>
                        ) : (
                          <Input
                            type="number"
                            min="0"
                            max={a.slots_available}
                            value={counts[a.agent_id] ?? 0}
                            onChange={(e) => handleCountChange(a.agent_id, a.slots_available, e.target.value)}
                            className="ml-auto h-8 w-20 text-right tabular-nums focus-visible:ring-sky-500"
                            aria-label={`Will assign for ${a.agent_name}`}
                            data-testid={`auto-assign-agent-count-${a.agent_id}`}
                          />
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        )}

        {previewLoading && !preview && (
          <p className="text-sm text-slate-400">Loading preview…</p>
        )}

        {!previewLoading && preview && agents.length === 0 && !result && (
          <p className="text-sm text-slate-500">No agent slots available or no unassigned leads in pool.</p>
        )}

        <DialogFooter>
          {result ? (
            <Button className="bg-sky-500 hover:bg-sky-600" onClick={() => onOpenChange(false)} data-testid="auto-assign-close">
              Done
            </Button>
          ) : (
            <>
              <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
              <Button
                className="bg-sky-500 hover:bg-sky-600"
                disabled={loading || previewLoading || !preview || totalSelected === 0}
                onClick={handleConfirm}
                data-testid="confirm-auto-assign-btn"
              >
                {loading ? "Assigning…" : `Assign ${totalSelected} leads`}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
