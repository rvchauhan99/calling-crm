import { useEffect, useState, useCallback } from "react";
import api, { formatApiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { PageHeader, EmptyState, PageLoader, StatusPill } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import { SearchableSelect } from "@/components/ui/searchable-select"
import { toast } from "sonner";
import { Plus, UsersRound, Pencil, Trash2 } from "lucide-react";

export default function Teams() {
  const { can } = useAuth();
  const [teams, setTeams] = useState(null);
  const [users, setUsers] = useState([]);
  const [show, setShow] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState({ name: "", supervisor_id: "", member_ids: [] });

  const load = useCallback(async () => {
    try { const { data } = await api.get("/teams"); setTeams(data.teams); }
    catch { setTeams([]); }
  }, []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { api.get("/users").then((r) => setUsers(r.data.users)).catch(() => {}); }, []);

  const openNew = () => { setEditing(null); setForm({ name: "", supervisor_id: "", member_ids: [] }); setShow(true); };
  const openEdit = (t) => { setEditing(t); setForm({ name: t.name, supervisor_id: t.supervisor_id || "", member_ids: t.member_ids || [] }); setShow(true); };

  const save = async () => {
    try {
      if (editing) await api.put(`/teams/${editing.id}`, form);
      else await api.post("/teams", form);
      toast.success("Saved"); setShow(false); load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  const remove = async (id) => {
    if (!window.confirm("Delete this team?")) return;
    await api.delete(`/teams/${id}`); toast.success("Deleted"); load();
  };
  const toggleMember = (id) => setForm((f) => ({ ...f, member_ids: f.member_ids.includes(id) ? f.member_ids.filter((x) => x !== id) : [...f.member_ids, id] }));

  if (!teams) return <PageLoader />;
  const callers = users.filter((u) => u.user_type === "caller");

  return (
    <div data-testid="teams-page">
      <PageHeader title="Teams" subtitle="Group callers under supervisors for TEAM-scoped data"
        actions={can("teams:create") && <Button className="bg-sky-500 hover:bg-sky-600" onClick={openNew} data-testid="new-team-btn"><Plus size={16} className="mr-1.5" /> New Team</Button>} />

      {teams.length === 0 ? (
        <EmptyState icon={UsersRound} title="No teams" description="Create a team and assign a supervisor + members." testid="teams-empty" />
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {teams.map((t) => (
            <div key={t.id} className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm" data-testid={`team-card-${t.id}`}>
              <div className="flex items-start justify-between">
                <div>
                  <p className="font-display font-semibold text-slate-800">{t.name}</p>
                  <p className="text-xs text-slate-400">Supervisor: {t.supervisor_name || "—"}</p>
                </div>
                {(can("teams:edit") || can("teams:delete")) && (
                  <div className="flex">
                    {can("teams:edit") && <Button variant="ghost" size="sm" onClick={() => openEdit(t)} data-testid={`edit-team-${t.id}`}><Pencil size={14} /></Button>}
                    {can("teams:delete") && <Button variant="ghost" size="sm" onClick={() => remove(t.id)} data-testid={`del-team-${t.id}`}><Trash2 size={14} className="text-red-500" /></Button>}
                  </div>
                )}
              </div>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {(t.member_names || []).map((m, i) => <StatusPill key={i} color="sky">{m}</StatusPill>)}
                {(!t.member_names || t.member_names.length === 0) && <span className="text-xs text-slate-300">No members</span>}
              </div>
            </div>
          ))}
        </div>
      )}

      <Dialog open={show} onOpenChange={setShow}>
        <DialogContent className="bg-white" data-testid="team-dialog">
          <DialogHeader><DialogTitle>{editing ? "Edit" : "New"} Team</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div><Label>Team name</Label><Input value={form.name} className="mt-1 focus-visible:ring-sky-500" onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="team-name" /></div>
            <div>
              <Label>Supervisor</Label>
              <SearchableSelect
                value={form.supervisor_id}
                onChange={(v) => setForm({ ...form, supervisor_id: v })}
                options={users.filter((u) => u.user_type === "admin").map((u) => ({ value: u.id, label: u.name }))}
                placeholder="Select supervisor"
                searchPlaceholder="Search supervisors…"
                label="Supervisor"
                testId="team-supervisor"
              />
            </div>
            <div>
              <Label>Members (callers)</Label>
              <div className="mt-1 max-h-48 space-y-1 overflow-y-auto rounded-md border border-slate-200 p-2">
                {callers.map((u) => (
                  <label key={u.id} className="flex items-center gap-2 rounded px-2 py-1.5 hover:bg-slate-50 cursor-pointer">
                    <Checkbox checked={form.member_ids.includes(u.id)} onCheckedChange={() => toggleMember(u.id)} data-testid={`team-member-${u.id}`} />
                    <span className="text-sm text-slate-700">{u.name}</span>
                  </label>
                ))}
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShow(false)}>Cancel</Button>
            <Button className="bg-sky-500 hover:bg-sky-600" onClick={save} data-testid="save-team-btn">Save</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
