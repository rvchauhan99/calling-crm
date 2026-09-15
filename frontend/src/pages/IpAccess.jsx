import { useEffect, useState, useCallback } from "react"
import api, { formatApiError } from "@/lib/api"
import { useAuth } from "@/context/AuthContext"
import { PageHeader, EmptyState, PageLoader, StatusPill, LoadingRegion } from "@/components/common"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog"
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table"
import { toast } from "sonner"
import { Plus, Pencil, Trash2, Shield, Copy } from "lucide-react"

const empty = {
  cidr: "",
  label: "",
  active: true,
}

export default function IpAccess() {
  const { can } = useAuth()
  const [list, setList] = useState(null)
  const [allowAll, setAllowAll] = useState(true)
  const [myIp, setMyIp] = useState("")
  const [loading, setLoading] = useState(true)
  const [show, setShow] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState(empty)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [listRes, ipRes] = await Promise.all([
        api.get("/ip-access"),
        api.get("/ip-access/my-ip"),
      ])
      setList(listRes.data.ip_access || [])
      setAllowAll(Boolean(listRes.data.allow_all))
      setMyIp(ipRes.data.ip || "")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load().catch(() => {}) }, [load])

  const handleCopyIp = async () => {
    if (!myIp) return
    try {
      await navigator.clipboard.writeText(myIp)
      toast.success("IP copied")
    } catch {
      toast.message(myIp)
    }
  }

  const openNew = () => {
    setEditing(null)
    setForm({ ...empty, cidr: myIp || "" })
    setShow(true)
  }

  const openEdit = (row) => {
    setEditing(row)
    setForm({
      cidr: row.cidr || "",
      label: row.label || "",
      active: Boolean(row.active),
    })
    setShow(true)
  }

  const save = async () => {
    try {
      const payload = {
        cidr: form.cidr.trim(),
        label: form.label.trim(),
        active: Boolean(form.active),
      }
      if (!payload.cidr) {
        toast.error("IP or CIDR is required")
        return
      }
      if (editing) await api.put(`/ip-access/${editing.id}`, payload)
      else await api.post("/ip-access", payload)
      toast.success("Saved")
      setShow(false)
      load()
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail))
    }
  }

  const remove = async (row) => {
    if (!window.confirm("Delete this IP access entry?")) return
    try {
      await api.delete(`/ip-access/${row.id}`)
      toast.success("Deleted")
      load()
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail))
    }
  }

  if (list === null) {
    return (
      <div data-testid="ip-access-page">
        <PageLoader />
      </div>
    )
  }

  return (
    <div data-testid="ip-access-page">
      <PageHeader
        title="IP Access"
        subtitle="Allow office and home networks · empty list allows all"
        actions={can("ip_access:create") && (
          <Button className="bg-sky-500 hover:bg-sky-600" onClick={openNew} data-testid="new-ip-access-btn">
            <Plus size={16} className="mr-1.5" /> New IP / CIDR
          </Button>
        )}
      />

      <div
        className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-sm"
        data-testid="ip-access-current-ip"
      >
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-slate-400">Your current IP</p>
          <p className="mt-0.5 font-mono text-sm text-slate-800" data-testid="ip-access-my-ip-value">
            {myIp || "—"}
          </p>
        </div>
        {myIp && (
          <Button variant="outline" size="sm" onClick={handleCopyIp} data-testid="copy-my-ip-btn">
            <Copy size={14} className="mr-1.5" /> Copy
          </Button>
        )}
      </div>

      {allowAll && (
        <div
          className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900"
          data-testid="ip-access-allow-all-banner"
        >
          No active entries — access is allowed from all networks. Add an office or home IP/CIDR to restrict access.
        </div>
      )}

      <div className="rounded-lg border border-slate-200 bg-white shadow-sm">
        <LoadingRegion loading={loading} hasData={true} testId="ip-access-page-results">
          {list.length === 0 ? (
            <EmptyState
              icon={Shield}
              title="No IP rules"
              description="Platform is open to all networks until you add an allowlist entry."
              testid="ip-access-empty"
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="bg-slate-50">
                  <TableHead>Label</TableHead>
                  <TableHead>IP / CIDR</TableHead>
                  <TableHead>Active</TableHead>
                  {(can("ip_access:edit") || can("ip_access:delete")) && (
                    <TableHead className="text-right">Actions</TableHead>
                  )}
                </TableRow>
              </TableHeader>
              <TableBody>
                {list.map((row) => (
                  <TableRow key={row.id} data-testid={`ip-access-row-${row.id}`}>
                    <TableCell className="font-medium">{row.label}</TableCell>
                    <TableCell className="font-mono text-sm">{row.cidr}</TableCell>
                    <TableCell>
                      {row.active
                        ? <StatusPill color="sky">Active</StatusPill>
                        : <StatusPill color="slate">Off</StatusPill>}
                    </TableCell>
                    {(can("ip_access:edit") || can("ip_access:delete")) && (
                      <TableCell className="text-right">
                        {can("ip_access:edit") && (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => openEdit(row)}
                            data-testid={`edit-ip-access-${row.id}`}
                          >
                            <Pencil size={15} />
                          </Button>
                        )}
                        {can("ip_access:delete") && (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => remove(row)}
                            data-testid={`del-ip-access-${row.id}`}
                          >
                            <Trash2 size={15} className="text-red-500" />
                          </Button>
                        )}
                      </TableCell>
                    )}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </LoadingRegion>
      </div>

      <Dialog open={show} onOpenChange={setShow}>
        <DialogContent className="bg-white" data-testid="ip-access-dialog">
          <DialogHeader>
            <DialogTitle>{editing ? "Edit" : "New"} IP Access</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label>Label</Label>
              <Input
                value={form.label}
                placeholder="Main office"
                className="mt-1 focus-visible:ring-sky-500"
                onChange={(e) => setForm({ ...form, label: e.target.value })}
                data-testid="ip-access-label"
              />
            </div>
            <div>
              <Label>IP or CIDR</Label>
              <Input
                value={form.cidr}
                placeholder="203.0.113.45 or 203.0.113.0/24"
                className="mt-1 font-mono focus-visible:ring-sky-500"
                onChange={(e) => setForm({ ...form, cidr: e.target.value })}
                data-testid="ip-access-cidr"
              />
              <p className="mt-1 text-xs text-slate-400">
                IPv4 or IPv6. Single IP or network range (CIDR).
              </p>
            </div>
            <div className="flex items-center justify-between rounded-md border border-slate-200 p-3">
              <p className="text-sm font-medium">Active</p>
              <Switch
                checked={form.active}
                onCheckedChange={(v) => setForm({ ...form, active: v })}
                data-testid="ip-access-active"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShow(false)}>Cancel</Button>
            <Button className="bg-sky-500 hover:bg-sky-600" onClick={save} data-testid="save-ip-access-btn">
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
