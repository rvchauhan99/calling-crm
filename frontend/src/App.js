import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import { Toaster } from "@/components/ui/sonner";
import Layout from "@/components/Layout";
import { Spinner } from "@/components/common";
import Login from "@/pages/Login";
import Dashboard from "@/pages/Dashboard";
import Leads from "@/pages/Leads";
import TodayCalls from "@/pages/TodayCalls";
import CallHistory from "@/pages/CallHistory";
import Dispositions from "@/pages/Dispositions";
import Clients from "@/pages/Clients";
import Ledger from "@/pages/Ledger";
import Reports from "@/pages/Reports";
import Users from "@/pages/Users";
import Teams from "@/pages/Teams";
import Roles from "@/pages/Roles";
import Pipeline from "@/pages/Pipeline";
import Followups from "@/pages/Followups";
import Audit from "@/pages/Audit";
import "@/App.css";

function Protected({ children }) {
  const { user } = useAuth();
  if (user === null)
    return <div className="flex h-screen items-center justify-center bg-slate-50"><Spinner className="h-8 w-8" /></div>;
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

function HomeRedirect() {
  const { menus, user } = useAuth();
  if (user === null) return null;
  const first = menus[0]?.path || "/dashboard";
  return <Navigate to={first} replace />;
}

function MenuGuard({ path, children }) {
  const { menus } = useAuth();
  const allowed = menus.some((m) => m.path === path);
  if (!allowed) return <Navigate to="/" replace />;
  return children;
}

function AppRoutes() {
  const g = (path, el) => <MenuGuard path={path}>{el}</MenuGuard>;
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<Protected><Layout /></Protected>}>
        <Route path="/" element={<HomeRedirect />} />
        <Route path="/dashboard" element={g("/dashboard", <Dashboard />)} />
        <Route path="/leads" element={g("/leads", <Leads />)} />
        <Route path="/today-calls" element={g("/today-calls", <TodayCalls />)} />
        <Route path="/call-history" element={g("/call-history", <CallHistory />)} />
        <Route path="/pipeline" element={g("/pipeline", <Pipeline />)} />
        <Route path="/followups" element={g("/followups", <Followups />)} />
        <Route path="/dispositions" element={g("/dispositions", <Dispositions />)} />
        <Route path="/clients" element={g("/clients", <Clients />)} />
        <Route path="/ledger" element={g("/ledger", <Ledger />)} />
        <Route path="/reports" element={g("/reports", <Reports />)} />
        <Route path="/users" element={g("/users", <Users />)} />
        <Route path="/teams" element={g("/teams", <Teams />)} />
        <Route path="/roles" element={g("/roles", <Roles />)} />
        <Route path="/audit" element={g("/audit", <Audit />)} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <AppRoutes />
        <Toaster position="top-right" richColors />
      </BrowserRouter>
    </AuthProvider>
  );
}
