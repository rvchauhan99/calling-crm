import { useState } from "react";
import { NavLink, useNavigate, Outlet } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { cn } from "@/lib/utils";
import {
  Gauge, Users, PhoneCall, History, Kanban, CalendarCheck, ListChecks,
  UserCog, Wallet, BarChart3, IdCard, UsersRound, ShieldCheck, FileSearch,
  LogOut, Menu as MenuIcon, X, PhoneOutgoing,
} from "lucide-react";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
  DropdownMenuLabel, DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";

const ICONS = {
  dashboard: Gauge, leads: Users, today_calls: PhoneCall, call_history: History,
  pipeline: Kanban, followups: CalendarCheck, dispositions: ListChecks,
  clients: UserCog, ledger: Wallet, reports: BarChart3, users: IdCard,
  teams: UsersRound, roles_menus: ShieldCheck, audit: FileSearch,
};

export default function Layout() {
  const { user, menus, logout } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);

  const groups = menus.reduce((acc, m) => {
    (acc[m.group] = acc[m.group] || []).push(m);
    return acc;
  }, {});

  const handleLogout = async () => { await logout(); navigate("/login"); };
  const initials = (user?.name || "U").split(" ").map((w) => w[0]).slice(0, 2).join("");

  const NavItems = () => (
    <nav className="flex-1 space-y-6 overflow-y-auto px-3 py-4">
      {Object.entries(groups).map(([group, items]) => (
        <div key={group}>
          <p className="px-3 pb-2 text-[10px] font-semibold uppercase tracking-wider text-slate-400">{group}</p>
          <div className="space-y-0.5">
            {items.map((m) => {
              const Icon = ICONS[m.key] || Gauge;
              return (
                <NavLink
                  key={m.key}
                  to={m.path}
                  data-testid={`nav-${m.key}`}
                  onClick={() => setOpen(false)}
                  className={({ isActive }) =>
                    cn("flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors duration-150",
                      isActive ? "bg-sky-500 text-white shadow-sm"
                        : "text-slate-600 hover:bg-sky-50 hover:text-sky-700")}
                >
                  <Icon size={18} strokeWidth={2} />
                  {m.label}
                </NavLink>
              );
            })}
          </div>
        </div>
      ))}
    </nav>
  );

  const Brand = () => (
    <div className="flex h-16 items-center gap-2.5 border-b border-slate-200 px-5">
      <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-sky-500 text-white">
        <PhoneOutgoing size={19} />
      </span>
      <div className="leading-tight">
        <p className="font-display text-base font-extrabold text-slate-900">CallingCRM</p>
        <p className="text-[10px] uppercase tracking-wider text-slate-400">Telecalling Suite</p>
      </div>
    </div>
  );

  return (
    <div className="flex h-screen bg-slate-50">
      {/* Desktop sidebar */}
      <aside className="hidden w-64 flex-col border-r border-slate-200 bg-white lg:flex">
        <Brand />
        <NavItems />
      </aside>

      {/* Mobile drawer */}
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-slate-900/40" onClick={() => setOpen(false)} />
          <aside className="absolute left-0 top-0 flex h-full w-64 flex-col bg-white">
            <div className="flex items-center justify-between">
              <Brand />
              <button className="pr-4" onClick={() => setOpen(false)} data-testid="close-drawer"><X size={20} /></button>
            </div>
            <NavItems />
          </aside>
        </div>
      )}

      <div className="flex flex-1 flex-col overflow-hidden">
        <header className="flex h-16 items-center justify-between border-b border-slate-200 bg-white px-4 lg:px-6">
          <button className="lg:hidden" onClick={() => setOpen(true)} data-testid="open-drawer"><MenuIcon size={22} /></button>
          <div className="hidden lg:block" />
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button className="flex items-center gap-2.5 rounded-full py-1 pl-1 pr-3 hover:bg-slate-100 transition-colors" data-testid="user-menu-trigger">
                <span className="flex h-8 w-8 items-center justify-center rounded-full bg-sky-500 text-xs font-bold text-white">{initials}</span>
                <span className="hidden text-left sm:block">
                  <span className="block text-sm font-semibold leading-tight text-slate-800">{user?.name}</span>
                  <span className="block text-[11px] leading-tight text-slate-400">{user?.role_name}</span>
                </span>
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-52 bg-white">
              <DropdownMenuLabel>
                <div className="text-sm font-semibold">{user?.name}</div>
                <div className="text-xs font-normal text-slate-400">{user?.email}</div>
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={handleLogout} data-testid="logout-btn" className="text-red-600 focus:text-red-600">
                <LogOut size={15} className="mr-2" /> Sign out
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </header>
        <main className="flex-1 overflow-y-auto p-4 lg:p-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
