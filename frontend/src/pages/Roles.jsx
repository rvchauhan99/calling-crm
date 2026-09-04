import { useEffect, useState, useCallback } from "react";
import api, { formatApiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { PageHeader, PageLoader, StatusPill } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";
import { SearchableSelect } from "@/components/ui/searchable-select"
import { toast } from "sonner";
import { Plus, ShieldCheck, Pencil, Trash2, Lock } from "lucide-react";

const ACTION_LABELS = {
  view: "View", create: "Create", edit: "Edit", delete: "Delete", import: "Import",
  export: "Export", assign: "Assign", log: "Log", post: "Post", reverse: "Reverse", convert: "Convert",
};

export default function Roles() {
  const { can } = useAuth();
  const [roles, setRoles] = useState(null);
  const [catalog, setCatalog] = useState([]);
  const [show, setShow] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState({ name: "", description: "", permissions: [], menus: [], data_scope: "OWN" });

  const load = useCallback(async () => {
    try { const { data } = await api.get("/roles"); setRoles(data.roles); }
    catch { setRoles([]); }
  }, []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { api.get("/menus/catalog").then((r) => setCatalog(r.data.menus)).catch(() => {}); }, []);

  const openNew = () => { setEditing(null); setForm({ name: "", description: "", permissions: [], menus: [], data_scope: "OWN" }); setShow(true); };
  const openEdit = (r) => { setEditing(r); setForm({ name: r.name, description: r.description, permissions: [...r.permissions], menus: [...r.menus], data_scope: r.data_scope }); setShow(true); };

  const save = async () => {
    try {
      if (editing) await api.put(`/roles/${editing.id}`, form);
      else await api.post("/roles", form);
      toast.success("Role saved"); setShow(false); load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  const remove = async (id) => {
    if (!window.confirm("Delete this role?")) return;
    try { await api.delete(`/roles/${id}`); toast.success("Deleted"); load(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const togglePerm = (perm) => setForm((f) => ({ ...f, permissions: f.permissions.includes(perm) ? f.permissions.filter((p) => p !== perm) : [...f.permissions, perm] }));
  const toggleMenu = (key) => setForm((f) => ({ ...f, menus: f.menus.includes(key) ? f.menus.filter((m) => m !== key) : [...f.menus, key] }));

  if (!roles) return <PageLoader />;

  return (
    <div data-testid="roles-page">
      <PageHeader title="Roles & Menus" subtitle="Deny-by-default RBAC · edit permissions without redeploy"
        actions={can("roles_menus:create") && <Button className="bg-sky-500 hover:bg-sky-600" onClick={openNew} data-testid="new-role-btn"><Plus size={16} className="mr-1.5" /> New Role</Button>} />

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {roles.map((r) => (
          <div key={r.id} className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm" data-testid={`role-card-${r.id}`}>
            <div className="flex items-start justify-between">
              <div>
                <p className="flex items-center gap-1.5 font-display font-semibold text-slate-800">
                  {r.is_system && <Lock size={13} className="text-slate-400" />}{r.name}
                </p>
                <p className="mt-0.5 text-xs text-slate-400">{r.description}</p>
              </div>
              {(can("roles_menus:edit") || can("roles_menus:delete")) && (
                <div className="flex">
                  {can("roles_menus:edit") && <Button variant="ghost" size="sm" onClick={() => openEdit(r)} data-testid={`edit-role-${r.id}`}><Pencil size={14} /></Button>}
                  {can("roles_menus:delete") && !r.is_system && <Button variant="ghost" size="sm" onClick={() => remove(r.id)} data-testid={`del-role-${r.id}`}><Trash2 size={14} className="text-red-500" /></Button>}
                </div>
              )}
            </div>
            <div className="mt-3 flex items-center gap-2">
              <StatusPill color="blue">{r.data_scope}</StatusPill>
              <StatusPill color="sky">{r.permissions.length} perms</StatusPill>
              <StatusPill color="slate">{r.user_count} users</StatusPill>
            </div>
          </div>
        ))}
      </div>

      <Dialog open={show} onOpenChange={setShow}>
        <DialogContent className="max-h-[90vh] overflow-y-auto bg-white sm:max-w-2xl" data-testid="role-dialog">
          <DialogHeader>
            <DialogTitle>{editing ? "Edit" : "New"} Role {editing?.is_system && <span className="text-xs font-normal text-slate-400">(system — name locked)</span>}</DialogTitle>
            <DialogDescription>Assign menus, granular permissions and a data scope.</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div><Label>Name</Label><Input value={form.name} disabled={editing?.is_system} className="mt-1 focus-visible:ring-sky-500" onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="role-name" /></div>
              <div>
                <Label>Data scope</Label>
                <SearchableSelect
                  value={form.data_scope}
                  onChange={(v) => setForm({ ...form, data_scope: v })}
                  options={[
                    { value: "OWN", label: "OWN — only their own records" },
                    { value: "TEAM", label: "TEAM — their team's records" },
                    { value: "ALL", label: "ALL — all records" },
                  ]}
                  placeholder="Select scope"
                  searchPlaceholder="Search scope…"
                  label="Data scope"
                  testId="role-scope"
                />
              </div>
            </div>
            <div><Label>Description</Label><Textarea value={form.description} rows={2} className="mt-1 focus-visible:ring-sky-500" onChange={(e) => setForm({ ...form, description: e.target.value })} data-testid="role-desc" /></div>

            <div>
              <Label className="mb-2 block">Menus & Permissions</Label>
              <div className="space-y-3">
                {catalog.map((m) => (
                  <div key={m.key} className="rounded-md border border-slate-200 p-3">
                    <label className="flex items-center gap-2">
                      <Checkbox checked={form.menus.includes(m.key)} onCheckedChange={() => toggleMenu(m.key)} data-testid={`menu-${m.key}`} />
                      <span className="font-medium text-sm text-slate-800">{m.label}</span>
                      <span className="text-[11px] text-slate-400">/{m.group}</span>
                    </label>
                    <div className="mt-2 flex flex-wrap gap-3 pl-6">
                      {m.actions.map((a) => {
                        const perm = `${m.key}:${a}`;
                        return (
                          <label key={perm} className="flex items-center gap-1.5 cursor-pointer">
                            <Checkbox checked={form.permissions.includes(perm)} onCheckedChange={() => togglePerm(perm)} data-testid={`perm-${perm}`} />
                            <span className="text-xs text-slate-600">{ACTION_LABELS[a] || a}</span>
                          </label>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShow(false)}>Cancel</Button>
            <Button className="bg-sky-500 hover:bg-sky-600" onClick={save} data-testid="save-role-btn">Save Role</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
