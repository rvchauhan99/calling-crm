import { useEffect, useState, useCallback } from "react"
import api, { formatApiError } from "@/lib/api"
import { useAuth } from "@/context/AuthContext"
import { PageHeader, EmptyState, PageLoader, StatusPill } from "@/components/common"
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
import { Plus, Share2, Pencil, Trash2 } from "lucide-react"

const empty = {
  name: "",
  order: 1,
  active: true,
  creatable: true,
}

export default function LeadSources() {
  const { can } = useAuth()
  const [list, setList] = useState(null)
  const [show, setShow] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState(empty)

  const load = useCallback(async () => {
    const { data } = await api.get("/lead-sources")
    setList(data.lead_sources)
  }, [])
  useEffect(() => { load().catch(() => {}) }, [load])

  const openNew = () => {
    setEditing(null)
    setForm({ ...empty, order: (list?.length || 0) + 1 })
    setShow(true)
  }
  const openEdit = (row) => {
    setEditing(row)
    setForm({
      name: row.name || "",
      order: row.order ?? 1,
      active: Boolean(row.active),
      creatable: Boolean(row.creatable),
    })
    setShow(true)
  }

  const save = async () => {
    try {
      const payload = {
        name: form.name.trim(),
        order: Number(form.order) || 1,
        active: Boolean(form.active),
        creatable: Boolean(form.creatable),
      }
      if (!payload.name) {
        toast.error("Name is required")
        return
      }
      if (editing) await api.put(`/lead-sources/${editing.id}`, payload)
      else await api.post("/lead-sources", payload)
      toast.success("Saved")
      setShow(false)
      load()
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail))
    }
  }
  const remove = async (row) => {
    if (row.is_system) {
      toast.error("System lead sources cannot be deleted")
      return
    }
    if (!window.confirm("Delete this lead source?")) return
    try {
      await api.delete(`/lead-sources/${row.id}`)
      toast.success("Deleted")
      load()
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail))
    }
  }

  if (!list) return <PageLoader />

  return (
    <div data-testid="lead-sources-page">
      <PageHeader
        title="Lead Sources"
        subtitle="CRM lead source master · used on leads, imports, and sheet sync"
        actions={can("lead_sources:create") && (
          <Button className="bg-sky-500 hover:bg-sky-600" onClick={openNew} data-testid="new-lead-source-btn">
            <Plus size={16} className="mr-1.5" /> New Lead Source
          </Button>
        )}
      />

      <div className="rounded-lg border border-slate-200 bg-white shadow-sm">
        {list.length === 0 ? (
          <EmptyState
            icon={Share2}
            title="No lead sources"
            description="Create CRM lead sources for forms and sheet sync."
            testid="lead-sources-empty"
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="bg-slate-50">
                <TableHead>Order</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Creatable</TableHead>
                <TableHead>Active</TableHead>
                <TableHead>System</TableHead>
                {(can("lead_sources:edit") || can("lead_sources:delete")) && (
                  <TableHead className="text-right">Actions</TableHead>
                )}
              </TableRow>
            </TableHeader>
            <TableBody>
              {list.map((row) => (
                <TableRow key={row.id} data-testid={`lead-source-row-${row.id}`}>
                  <TableCell className="tabular text-slate-500">{row.order}</TableCell>
                  <TableCell className="font-medium">{row.name}</TableCell>
                  <TableCell>
                    {row.creatable
                      ? <StatusPill color="sky">Yes</StatusPill>
                      : <StatusPill color="slate">No</StatusPill>}
                  </TableCell>
                  <TableCell>
                    {row.active
                      ? <StatusPill color="sky">Active</StatusPill>
                      : <StatusPill color="slate">Off</StatusPill>}
                  </TableCell>
                  <TableCell>
                    {row.is_system
                      ? <StatusPill color="amber">System</StatusPill>
                      : <span className="text-slate-300">—</span>}
                  </TableCell>
                  {(can("lead_sources:edit") || can("lead_sources:delete")) && (
                    <TableCell className="text-right">
                      {can("lead_sources:edit") && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => openEdit(row)}
                          data-testid={`edit-lead-source-${row.id}`}
                        >
                          <Pencil size={15} />
                        </Button>
                      )}
                      {can("lead_sources:delete") && !row.is_system && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => remove(row)}
                          data-testid={`del-lead-source-${row.id}`}
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
      </div>

      <Dialog open={show} onOpenChange={setShow}>
        <DialogContent className="bg-white" data-testid="lead-source-dialog">
          <DialogHeader>
            <DialogTitle>{editing ? "Edit" : "New"} Lead Source</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label>Name</Label>
              <Input
                value={form.name}
                className="mt-1 focus-visible:ring-sky-500"
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                data-testid="lead-source-name"
              />
            </div>
            <div>
              <Label>Order</Label>
              <Input
                type="number"
                value={form.order}
                className="mt-1 focus-visible:ring-sky-500"
                onChange={(e) => setForm({ ...form, order: Number(e.target.value) })}
                data-testid="lead-source-order"
              />
            </div>
            <div className="flex items-center justify-between rounded-md border border-slate-200 p-3">
              <div>
                <p className="text-sm font-medium">Creatable on lead form</p>
                <p className="text-xs text-slate-400">Off means import/sheet only (e.g. Import)</p>
              </div>
              <Switch
                checked={form.creatable}
                onCheckedChange={(v) => setForm({ ...form, creatable: v })}
                disabled={editing?.name === "Import" && editing?.is_system}
                data-testid="lead-source-creatable"
              />
            </div>
            <div className="flex items-center justify-between rounded-md border border-slate-200 p-3">
              <p className="text-sm font-medium">Active</p>
              <Switch
                checked={form.active}
                onCheckedChange={(v) => setForm({ ...form, active: v })}
                data-testid="lead-source-active"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShow(false)}>Cancel</Button>
            <Button className="bg-sky-500 hover:bg-sky-600" onClick={save} data-testid="save-lead-source-btn">
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
