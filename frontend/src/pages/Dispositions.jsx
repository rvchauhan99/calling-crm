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
import { SearchableSelect } from "@/components/ui/searchable-select"
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table"
import { toast } from "sonner"
import { Plus, ListChecks, Pencil, Trash2 } from "lucide-react"

const STAGES = ["New", "Contacted", "Qualified", "Proposal", "Won", "Lost"]

const empty = {
  name: "",
  slot: 1,
  type: "carry_forward",
  requires_acw: false,
  color: "#0EA5E9",
  active: true,
  default_pipeline_stage: "",
  converts_to_client: false,
}

export default function Dispositions() {
  const { can } = useAuth()
  const [list, setList] = useState(null)
  const [show, setShow] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState(empty)

  const load = useCallback(async () => {
    const { data } = await api.get("/dispositions")
    setList(data.dispositions)
  }, [])
  useEffect(() => { load().catch(() => {}) }, [load])

  const openNew = () => {
    setEditing(null)
    setForm({ ...empty, slot: (list?.length || 0) + 1 })
    setShow(true)
  }
  const openEdit = (d) => {
    setEditing(d)
    setForm({
      ...empty,
      ...d,
      default_pipeline_stage: d.default_pipeline_stage || "",
      converts_to_client: Boolean(d.converts_to_client),
    })
    setShow(true)
  }

  const save = async () => {
    try {
      const payload = {
        ...form,
        default_pipeline_stage: form.converts_to_client
          ? "Won"
          : (form.default_pipeline_stage || null),
        converts_to_client: Boolean(form.converts_to_client),
      }
      if (editing) await api.put(`/dispositions/${editing.id}`, payload)
      else await api.post("/dispositions", payload)
      toast.success("Saved")
      setShow(false)
      load()
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail))
    }
  }
  const remove = async (id) => {
    if (!window.confirm("Delete this disposition?")) return
    await api.delete(`/dispositions/${id}`)
    toast.success("Deleted")
    load()
  }

  if (!list) return <PageLoader />

  return (
    <div data-testid="dispositions-page">
      <PageHeader
        title="Responses"
        subtitle="Call disposition slots · pipeline mapping · carry-forward & ACW"
        actions={can("dispositions:create") && (
          <Button className="bg-sky-500 hover:bg-sky-600" onClick={openNew} data-testid="new-disposition-btn">
            <Plus size={16} className="mr-1.5" /> New Response
          </Button>
        )}
      />

      <div className="rounded-lg border border-slate-200 bg-white shadow-sm">
        {list.length === 0 ? (
          <EmptyState icon={ListChecks} title="No dispositions" description="Create call outcome slots agents can select." testid="disp-empty" />
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="bg-slate-50">
                <TableHead>Slot</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Pipeline</TableHead>
                <TableHead>Client</TableHead>
                <TableHead>ACW</TableHead>
                <TableHead>Active</TableHead>
                {(can("dispositions:edit") || can("dispositions:delete")) && (
                  <TableHead className="text-right">Actions</TableHead>
                )}
              </TableRow>
            </TableHeader>
            <TableBody>
              {list.map((d) => (
                <TableRow key={d.id} data-testid={`disp-row-${d.id}`}>
                  <TableCell className="tabular text-slate-500">{d.slot}</TableCell>
                  <TableCell className="font-medium">
                    <span className="flex items-center gap-2">
                      <span className="h-3 w-3 rounded-full" style={{ background: d.color }} />
                      {d.name}
                    </span>
                  </TableCell>
                  <TableCell>
                    <StatusPill color={d.type === "carry_forward" ? "sky" : "amber"}>
                      {d.type === "carry_forward" ? "Carry forward" : "Non carry"}
                    </StatusPill>
                  </TableCell>
                  <TableCell>
                    {d.default_pipeline_stage
                      ? <StatusPill color="sky">{d.default_pipeline_stage}</StatusPill>
                      : <span className="text-slate-300">—</span>}
                  </TableCell>
                  <TableCell>
                    {d.converts_to_client
                      ? <StatusPill color="amber">Yes</StatusPill>
                      : <span className="text-slate-300">—</span>}
                  </TableCell>
                  <TableCell>
                    {d.requires_acw
                      ? <StatusPill color="amber">Yes</StatusPill>
                      : <span className="text-slate-300">—</span>}
                  </TableCell>
                  <TableCell>
                    {d.active
                      ? <StatusPill color="sky">Active</StatusPill>
                      : <StatusPill color="slate">Off</StatusPill>}
                  </TableCell>
                  {(can("dispositions:edit") || can("dispositions:delete")) && (
                    <TableCell className="text-right">
                      {can("dispositions:edit") && (
                        <Button variant="ghost" size="sm" onClick={() => openEdit(d)} data-testid={`edit-disp-${d.id}`}>
                          <Pencil size={15} />
                        </Button>
                      )}
                      {can("dispositions:delete") && (
                        <Button variant="ghost" size="sm" onClick={() => remove(d.id)} data-testid={`del-disp-${d.id}`}>
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
        <DialogContent className="bg-white" data-testid="disp-dialog">
          <DialogHeader>
            <DialogTitle>{editing ? "Edit" : "New"} Response</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label>Name</Label>
              <Input
                value={form.name}
                className="mt-1 focus-visible:ring-sky-500"
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                data-testid="disp-name"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Slot</Label>
                <Input
                  type="number"
                  value={form.slot}
                  className="mt-1 focus-visible:ring-sky-500"
                  onChange={(e) => setForm({ ...form, slot: Number(e.target.value) })}
                  data-testid="disp-slot"
                />
              </div>
              <div>
                <Label>Color</Label>
                <Input
                  type="color"
                  value={form.color}
                  className="mt-1 h-10"
                  onChange={(e) => setForm({ ...form, color: e.target.value })}
                  data-testid="disp-color"
                />
              </div>
            </div>
            <div>
              <Label>Type</Label>
              <SearchableSelect
                value={form.type}
                onChange={(v) => setForm({ ...form, type: v })}
                options={[
                  { value: "carry_forward", label: "Carry forward (stays retry-eligible)" },
                  { value: "non_carry_forward", label: "Non carry-forward (leaves queue)" },
                ]}
                placeholder="Select type"
                searchPlaceholder="Search type…"
                label="Type"
                testId="disp-type"
              />
            </div>
            <div>
              <SearchableSelect
                value={form.converts_to_client ? "Won" : (form.default_pipeline_stage || "none")}
                onChange={(v) => setForm({
                  ...form,
                  default_pipeline_stage: v === "none" ? "" : v,
                })}
                options={[
                  { value: "none", label: "No default (manual)" },
                  ...STAGES.map((s) => ({ value: s, label: s })),
                ]}
                placeholder="Pipeline stage"
                searchPlaceholder="Search stages…"
                label="Default pipeline stage"
                testId="disp-pipeline-stage"
                disabled={form.converts_to_client}
              />
              {form.converts_to_client && (
                <p className="mt-1 text-xs text-slate-500">Locked to Won when converting to client</p>
              )}
            </div>
            <div className="flex items-center justify-between rounded-md border border-slate-200 p-3">
              <div>
                <p className="text-sm font-medium">Converts to client</p>
                <p className="text-xs text-slate-400">Creates client and sets stage to Won on log</p>
              </div>
              <Switch
                checked={form.converts_to_client}
                onCheckedChange={(v) => setForm({
                  ...form,
                  converts_to_client: v,
                  default_pipeline_stage: v ? "Won" : form.default_pipeline_stage,
                })}
                data-testid="disp-converts"
              />
            </div>
            <div className="flex items-center justify-between rounded-md border border-slate-200 p-3">
              <div>
                <p className="text-sm font-medium">Requires ACW</p>
                <p className="text-xs text-slate-400">Marks after-call work pending (does not block calling)</p>
              </div>
              <Switch
                checked={form.requires_acw}
                onCheckedChange={(v) => setForm({ ...form, requires_acw: v })}
                data-testid="disp-acw"
              />
            </div>
            <div className="flex items-center justify-between rounded-md border border-slate-200 p-3">
              <p className="text-sm font-medium">Active</p>
              <Switch
                checked={form.active}
                onCheckedChange={(v) => setForm({ ...form, active: v })}
                data-testid="disp-active"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShow(false)}>Cancel</Button>
            <Button className="bg-sky-500 hover:bg-sky-600" onClick={save} data-testid="save-disp-btn">Save</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
