import { useEffect, useState, useCallback } from "react";
import api, { formatApiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { PageHeader, EmptyState, PageLoader, StatusPill } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { toast } from "sonner";
import { Plus, IdCard, Pencil, Trash2 } from "lucide-react";

const empty = { name: "", email: "", password: "", role_id: "", user_type: "caller", daily_quota: 25, active: true };

export default function Users() {
  const { can } = useAuth();
  const [users, setUsers] = useState(null);
  const [roles, setRoles] = useState([]);
  const [tab, setTab] = useState("all");
  const [show, setShow] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(empty);

  const load = useCallback(async () => {
    try {
      const q = tab === "all" ? "" : `?user_type=${tab}`;
      const { data } = await api.get(`/users${q}`);
      setUsers(data.users);
    } catch { setUsers([]); }
  }, [tab]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { api.get("/roles").then((r) => setRoles(r.data.roles)).catch(() => {}); }, []);

  const openNew = () => { setEditing(null); setForm({ ...empty, role_id: roles[0]?.id || "" }); setShow(true); };
  const openEdit = (u) => { setEditing(u); setForm({ ...u, password: "" }); setShow(true); };

  const save = async () => {
    try {
      if (editing) await api.put(`/users/${editing.id}`, form);
      else await api.post("/users", form);
      toast.success("Saved"); setShow(false); load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  const remove = async (id) => {
    if (!window.confirm("Deactivate this user?")) return;
    try { await api.delete(`/users/${id}`); toast.success("Deactivated"); load(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  if (!users) return <PageLoader />;

  return (
    <div data-testid="users-page">
      <PageHeader title="Users" subtitle="Callers, affiliates & admins"
        actions={can("users:create") && <Button className="bg-sky-500 hover:bg-sky-600" onClick={openNew} data-testid="new-user-btn"><Plus size={16} className="mr-1.5" /> New User</Button>} />

      <Tabs value={tab} onValueChange={setTab} className="mb-4">
        <TabsList className="bg-slate-100">
          <TabsTrigger value="all" data-testid="tab-all">All</TabsTrigger>
          <TabsTrigger value="caller" data-testid="tab-callers">Callers</TabsTrigger>
          <TabsTrigger value="affiliate" data-testid="tab-affiliates">Affiliates</TabsTrigger>
          <TabsTrigger value="admin" data-testid="tab-admins">Admins</TabsTrigger>
        </TabsList>
      </Tabs>

      <div className="rounded-lg border border-slate-200 bg-white shadow-sm">
        {users.length === 0 ? (
          <EmptyState icon={IdCard} title="No users" description="Add callers, affiliates or admins." testid="users-empty" />
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="bg-slate-50">
                <TableHead>Name</TableHead><TableHead>Email</TableHead><TableHead>Role</TableHead>
                <TableHead>Type</TableHead><TableHead>Quota</TableHead><TableHead>Status</TableHead>
                {(can("users:edit") || can("users:delete")) && <TableHead className="text-right">Actions</TableHead>}
              </TableRow>
            </TableHeader>
            <TableBody>
              {users.map((u) => (
                <TableRow key={u.id} data-testid={`user-row-${u.id}`}>
                  <TableCell className="font-medium text-slate-800">{u.name}</TableCell>
                  <TableCell className="text-slate-600">{u.email}</TableCell>
                  <TableCell><StatusPill color="blue">{u.role_name || "—"}</StatusPill></TableCell>
                  <TableCell className="capitalize text-slate-500">{u.user_type}</TableCell>
                  <TableCell className="tabular text-slate-500">{u.daily_quota || 0}</TableCell>
                  <TableCell>{u.active ? <StatusPill color="sky">Active</StatusPill> : <StatusPill color="slate">Disabled</StatusPill>}</TableCell>
                  {(can("users:edit") || can("users:delete")) && (
                    <TableCell className="text-right">
                      {can("users:edit") && <Button variant="ghost" size="sm" onClick={() => openEdit(u)} data-testid={`edit-user-${u.id}`}><Pencil size={15} /></Button>}
                      {can("users:delete") && <Button variant="ghost" size="sm" onClick={() => remove(u.id)} data-testid={`del-user-${u.id}`}><Trash2 size={15} className="text-red-500" /></Button>}
                    </TableCell>
                  )}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>

      <Dialog open={show} onOpenChange={setShow}>
        <DialogContent className="bg-white" data-testid="user-dialog">
          <DialogHeader><DialogTitle>{editing ? "Edit" : "New"} User</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div><Label>Name</Label><Input value={form.name} className="mt-1 focus-visible:ring-sky-500" onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="user-name" /></div>
            <div><Label>Email</Label><Input type="email" value={form.email} className="mt-1 focus-visible:ring-sky-500" onChange={(e) => setForm({ ...form, email: e.target.value })} data-testid="user-email" /></div>
            <div><Label>{editing ? "New password (optional)" : "Password"}</Label><Input type="password" value={form.password} className="mt-1 focus-visible:ring-sky-500" onChange={(e) => setForm({ ...form, password: e.target.value })} data-testid="user-password" /></div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Role</Label>
                <Select value={form.role_id} onValueChange={(v) => setForm({ ...form, role_id: v })}>
                  <SelectTrigger className="mt-1" data-testid="user-role"><SelectValue placeholder="Role" /></SelectTrigger>
                  <SelectContent className="bg-white">{roles.map((r) => <SelectItem key={r.id} value={r.id}>{r.name}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <div>
                <Label>Type</Label>
                <Select value={form.user_type} onValueChange={(v) => setForm({ ...form, user_type: v })}>
                  <SelectTrigger className="mt-1" data-testid="user-type"><SelectValue /></SelectTrigger>
                  <SelectContent className="bg-white">
                    <SelectItem value="caller">Caller</SelectItem>
                    <SelectItem value="affiliate">Affiliate</SelectItem>
                    <SelectItem value="admin">Admin</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div><Label>Daily lead quota</Label><Input type="number" value={form.daily_quota} className="mt-1 focus-visible:ring-sky-500" onChange={(e) => setForm({ ...form, daily_quota: Number(e.target.value) })} data-testid="user-quota" /></div>
            <div className="flex items-center justify-between rounded-md border border-slate-200 p-3">
              <p className="text-sm font-medium">Active</p>
              <Switch checked={form.active} onCheckedChange={(v) => setForm({ ...form, active: v })} data-testid="user-active" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShow(false)}>Cancel</Button>
            <Button className="bg-sky-500 hover:bg-sky-600" onClick={save} data-testid="save-user-btn">Save</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
