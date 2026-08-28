import { useEffect, useState } from "react";
import api from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { PageHeader, StatCard, PageLoader, Money } from "@/components/common";
import { Users, PhoneCall, UserCog, TrendingUp, Wallet, Target } from "lucide-react";
import {
  BarChart, Bar, LineChart, Line, PieChart, Pie, Cell, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";

const PIE = ["#0EA5E9", "#0369A1", "#38BDF8", "#7DD3FC", "#F59E0B", "#EF4444", "#94A3B8", "#0284C7"];

export default function Dashboard() {
  const { user } = useAuth();
  const [data, setData] = useState(null);

  useEffect(() => { api.get("/dashboard").then((r) => setData(r.data)).catch(() => {}); }, []);
  if (!data) return <PageLoader />;
  const k = data.kpis;
  const isAffiliate = user?.user_type === "affiliate";

  return (
    <div data-testid="dashboard-page">
      <PageHeader title="Dashboard" subtitle="Live operational overview (IST)" />

      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
        {!isAffiliate && <StatCard testid="kpi-leads" label="Total Leads" value={k.total_leads} hint={`${k.active_leads} active`} icon={Users} />}
        {!isAffiliate && <StatCard testid="kpi-calls" label="Calls Logged" value={k.total_calls} hint={`${k.calls_today} today`} icon={PhoneCall} accent="blue" />}
        <StatCard testid="kpi-clients" label="Clients" value={k.total_clients} hint={`${k.ftd_clients} with FTD`} icon={UserCog} />
        {!isAffiliate && <StatCard testid="kpi-conv" label="Conversion" value={`${k.conversion_rate}%`} icon={Target} accent="amber" />}
        <StatCard testid="kpi-credit" label="Deposits" value={<Money value={k.ledger_credit} />} icon={Wallet} />
        <StatCard testid="kpi-net" label="Net Balance" value={<Money value={k.net_balance} />} hint={`₹${k.ledger_debit.toLocaleString("en-IN")} withdrawn`} icon={TrendingUp} accent="blue" />
      </div>

      {!isAffiliate && (
      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm lg:col-span-2">
          <h3 className="font-display text-base font-semibold text-slate-800">Calls — last 7 days</h3>
          <div className="mt-4 h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data.calls_trend}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                <XAxis dataKey="date" stroke="#94a3b8" fontSize={12} tickLine={false} />
                <YAxis stroke="#94a3b8" fontSize={12} tickLine={false} axisLine={false} allowDecimals={false} />
                <Tooltip contentStyle={{ borderRadius: 8, border: "1px solid #e2e8f0" }} />
                <Line type="monotone" dataKey="calls" stroke="#0EA5E9" strokeWidth={2.5} dot={{ r: 3, fill: "#0EA5E9" }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <h3 className="font-display text-base font-semibold text-slate-800">Disposition mix</h3>
          <div className="mt-4 h-64">
            {data.disposition_mix.length === 0 ? (
              <div className="flex h-full items-center justify-center text-sm text-slate-400">No calls yet</div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={data.disposition_mix} dataKey="value" nameKey="name" innerRadius={45} outerRadius={80} paddingAngle={2}>
                    {data.disposition_mix.map((_, i) => <Cell key={i} fill={PIE[i % PIE.length]} />)}
                  </Pie>
                  <Tooltip contentStyle={{ borderRadius: 8, border: "1px solid #e2e8f0" }} />
                </PieChart>
              </ResponsiveContainer>
            )}
          </div>
          <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
            {data.disposition_mix.slice(0, 6).map((d, i) => (
              <span key={d.name} className="flex items-center gap-1.5 text-xs text-slate-500">
                <span className="h-2.5 w-2.5 rounded-full" style={{ background: PIE[i % PIE.length] }} />{d.name}
              </span>
            ))}
          </div>
        </div>
      </div>
      )}
    </div>
  );
}
