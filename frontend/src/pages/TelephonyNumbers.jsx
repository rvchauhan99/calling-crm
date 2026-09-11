import { useCallback, useEffect, useState } from "react"
import api, { formatApiError } from "@/lib/api"
import { useAuth } from "@/context/AuthContext"
import { PageHeader, EmptyState, PageLoader, StatusPill } from "@/components/common"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog"
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table"
import { toast } from "sonner"
import { Plus, Pencil, Trash2, Phone, ListTree, Lock } from "lucide-react"

const emptyNumber = {
  e164: "",
  label: "",
  active: true,
  is_default: false,
}

const emptyIvr = {
  greeting_text: "Thank you for calling. Press 1 for sales, 2 for support.",
  menu: [
    { digit: "1", label: "Sales", action: "queue", target: "sales" },
    { digit: "2", label: "Support", action: "queue", target: "support" },
  ],
  missed_create_lead: true,
  active: true,
}

export default function TelephonyNumbers() {
  const { can } = useAuth()
  const [list, setList] = useState(null)
  const [status, setStatus] = useState(null)
  const [show, setShow] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState(emptyNumber)
  const [ivrOpen, setIvrOpen] = useState(false)
  const [ivrDid, setIvrDid] = useState(null)
  const [ivrForm, setIvrForm] = useState(emptyIvr)

  const load = useCallback(async () => {
    const [nums, st] = await Promise.all([
      api.get("/telephony/numbers"),
      api.get("/telephony/status").catch(() => ({ data: null })),
    ])
    setList(nums.data.numbers)
    setStatus(st.data)
  }, [])

  useEffect(() => {
    load().catch(() => setList([]))
  }, [load])

  const telephonyEnabled = Boolean(status?.ui_enabled ?? status?.enabled)

  const openNew = () => {
    if (!telephonyEnabled) {
      toast.error("Cloud calling is inactive until provider keys are configured")
      return
    }
    setEditing(null)
    setForm({ ...emptyNumber })
    setShow(true)
  }

  const openEdit = (row) => {
    if (!telephonyEnabled) {
      toast.error("Cloud calling is inactive until provider keys are configured")
      return
    }
    setEditing(row)
    setForm({
      e164: row.e164 || "",
      label: row.label || "",
      active: Boolean(row.active),
      is_default: Boolean(row.is_default),
    })
    setShow(true)
  }

  const save = async () => {
    try {
      const payload = {
        e164: form.e164.trim(),
        label: form.label.trim(),
        active: Boolean(form.active),
        is_default: Boolean(form.is_default),
      }
      if (!payload.e164) {
        toast.error("E.164 number required")
        return
      }
      if (editing) await api.put(`/telephony/numbers/${editing.id}`, payload)
      else await api.post("/telephony/numbers", payload)
      toast.success("Saved")
      setShow(false)
      load()
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail))
    }
  }

  const remove = async (row) => {
    if (!telephonyEnabled) {
      toast.error("Cloud calling is inactive until provider keys are configured")
      return
    }
    if (!window.confirm(`Delete ${row.e164}?`)) return
    try {
      await api.delete(`/telephony/numbers/${row.id}`)
      toast.success("Deleted")
      load()
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail))
    }
  }

  const openIvr = async (row) => {
    if (!telephonyEnabled) {
      toast.error("Cloud calling is inactive until provider keys are configured")
      return
    }
    setIvrDid(row)
    try {
      const { data } = await api.get(`/telephony/ivr/${row.id}`)
      setIvrForm({
        greeting_text: data.greeting_text || emptyIvr.greeting_text,
        menu: data.menu?.length ? data.menu : emptyIvr.menu,
        missed_create_lead: data.missed_create_lead !== false,
        active: data.active !== false,
      })
    } catch {
      setIvrForm({ ...emptyIvr, menu: [...emptyIvr.menu] })
    }
    setIvrOpen(true)
  }

  const saveIvr = async () => {
    try {
      await api.put("/telephony/ivr", {
        did_id: ivrDid.id,
        greeting_text: ivrForm.greeting_text,
        menu: ivrForm.menu,
        missed_create_lead: ivrForm.missed_create_lead,
        active: ivrForm.active,
      })
      toast.success("IVR saved")
      setIvrOpen(false)
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail))
    }
  }

  const updateMenuRow = (idx, key, value) => {
    setIvrForm((prev) => {
      const menu = prev.menu.map((m, i) => (i === idx ? { ...m, [key]: value } : m))
      return { ...prev, menu }
    })
  }

  if (list === null) return <PageLoader />

  return (
    <div className="space-y-6" data-testid="telephony-numbers-page">
      <PageHeader
        title="Phone Numbers"
        description="Virtual DIDs, default CLI, and single-level IVR routing."
        actions={
          can("telephony_numbers:create") && telephonyEnabled && (
            <Button onClick={openNew} data-testid="telephony-add-number">
              <Plus size={16} className="mr-1.5" /> Add number
            </Button>
          )
        }
      />

      {status && (
        <div
          className={
            telephonyEnabled
              ? "rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700"
              : "rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900"
          }
          data-testid="telephony-status-banner"
        >
          {!telephonyEnabled && (
            <p className="mb-1 flex items-center gap-1.5 font-semibold" data-testid="telephony-inactive-banner">
              <Lock size={14} /> Cloud calling inactive
            </p>
          )}
          <p>
            Provider: <strong>{status.adapter}</strong>
            {" · "}
            Active calls: {status.active_calls}/{status.max_concurrent}
            {status.did ? ` · Env DID: ${status.did}` : ""}
            {telephonyEnabled
              ? (status.livekit_configured ? " · LiveKit configured" : "")
              : " · Waiting for Udyam/Plivo registration and LIVEKIT_* keys"}
          </p>
          {!telephonyEnabled && status.inactive_reason && (
            <p className="mt-1 text-xs text-amber-800">{status.inactive_reason}</p>
          )}
        </div>
      )}

      {!list.length ? (
        <EmptyState
          icon={Phone}
          title="No numbers yet"
          description="Add your Plivo DID after KYC, or a placeholder for mock tests."
        />
      ) : (
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Number</TableHead>
                <TableHead>Label</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Default</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {list.map((row) => (
                <TableRow key={row.id} data-testid={`telephony-number-row-${row.id}`}>
                  <TableCell className="font-mono text-sm">{row.e164}</TableCell>
                  <TableCell>{row.label}</TableCell>
                  <TableCell>
                    <StatusPill color={row.active ? "emerald" : "slate"}>
                      {row.active ? "Active" : "Off"}
                    </StatusPill>
                  </TableCell>
                  <TableCell>{row.is_default ? "Yes" : "—"}</TableCell>
                  <TableCell className="text-right space-x-1">
                    {telephonyEnabled && can("telephony_numbers:edit") && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => openIvr(row)}
                        data-testid={`telephony-ivr-${row.id}`}
                      >
                        <ListTree size={14} className="mr-1" /> IVR
                      </Button>
                    )}
                    {telephonyEnabled && can("telephony_numbers:edit") && (
                      <Button size="sm" variant="ghost" onClick={() => openEdit(row)} aria-label="Edit">
                        <Pencil size={14} />
                      </Button>
                    )}
                    {telephonyEnabled && can("telephony_numbers:delete") && (
                      <Button size="sm" variant="ghost" onClick={() => remove(row)} aria-label="Delete">
                        <Trash2 size={14} />
                      </Button>
                    )}
                    {!telephonyEnabled && (
                      <span className="text-xs text-slate-400" data-testid="telephony-row-locked">Locked</span>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <Dialog open={show} onOpenChange={setShow}>
        <DialogContent data-testid="telephony-number-dialog">
          <DialogHeader>
            <DialogTitle>{editing ? "Edit number" : "Add number"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label htmlFor="did-e164">E.164 number</Label>
              <Input
                id="did-e164"
                data-testid="telephony-e164"
                value={form.e164}
                onChange={(e) => setForm({ ...form, e164: e.target.value })}
                placeholder="+9198XXXXXXXX"
              />
            </div>
            <div>
              <Label htmlFor="did-label">Label</Label>
              <Input
                id="did-label"
                data-testid="telephony-label"
                value={form.label}
                onChange={(e) => setForm({ ...form, label: e.target.value })}
              />
            </div>
            <div className="flex items-center justify-between">
              <Label>Active</Label>
              <Switch
                checked={form.active}
                onCheckedChange={(v) => setForm({ ...form, active: v })}
                data-testid="telephony-active"
              />
            </div>
            <div className="flex items-center justify-between">
              <Label>Default outbound CLI</Label>
              <Switch
                checked={form.is_default}
                onCheckedChange={(v) => setForm({ ...form, is_default: v })}
                data-testid="telephony-default"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShow(false)}>Cancel</Button>
            <Button onClick={save} data-testid="telephony-save-number">Save</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={ivrOpen} onOpenChange={setIvrOpen}>
        <DialogContent className="max-w-lg" data-testid="telephony-ivr-dialog">
          <DialogHeader>
            <DialogTitle>IVR — {ivrDid?.e164}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label htmlFor="ivr-greeting">Greeting</Label>
              <Textarea
                id="ivr-greeting"
                data-testid="telephony-ivr-greeting"
                value={ivrForm.greeting_text}
                onChange={(e) => setIvrForm({ ...ivrForm, greeting_text: e.target.value })}
                rows={3}
              />
            </div>
            {ivrForm.menu.map((m, idx) => (
              <div key={idx} className="grid grid-cols-4 gap-2" data-testid={`telephony-ivr-menu-${idx}`}>
                <Input
                  value={m.digit}
                  onChange={(e) => updateMenuRow(idx, "digit", e.target.value)}
                  placeholder="Digit"
                  aria-label="Digit"
                />
                <Input
                  className="col-span-1"
                  value={m.label}
                  onChange={(e) => updateMenuRow(idx, "label", e.target.value)}
                  placeholder="Label"
                  aria-label="Label"
                />
                <Input
                  className="col-span-2"
                  value={m.target}
                  onChange={(e) => updateMenuRow(idx, "target", e.target.value)}
                  placeholder="Queue target"
                  aria-label="Target"
                />
              </div>
            ))}
            <div className="flex items-center justify-between">
              <Label>Create lead on missed inbound</Label>
              <Switch
                checked={ivrForm.missed_create_lead}
                onCheckedChange={(v) => setIvrForm({ ...ivrForm, missed_create_lead: v })}
                data-testid="telephony-ivr-missed"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIvrOpen(false)}>Cancel</Button>
            <Button onClick={saveIvr} data-testid="telephony-save-ivr">Save IVR</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
