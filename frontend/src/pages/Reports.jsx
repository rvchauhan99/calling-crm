import { useEffect, useState } from "react";
import api, { API, getToken } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { PageHeader, PageLoader, StatusPill, Money } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import { Download } from "lucide-react";

export default function Reports() {
  const { can, user } = useAuth();
  const [tab, setTab] = useState(user?.user_type === "affiliate" ? "affiliate" : "caller");
  const [caller, setCaller] = useState(null);
  const [affiliate, setAffiliate] = useState(null);
  const [company, setCompany] = useState(null);

  useEffect(() => {
    api.get("/reports/caller").then((r) => setCaller(r.data.rows)).catch(() => setCaller([]));
    api.get("/reports/affiliate").then((r) => setAffiliate(r.data.rows)).catch(() => setAffiliate([]));
    api.get("/reports/company").then((r) => setCompany(r.data.rows)).catch(() => setCompany([]));
  }, []);

  const exportCsv = async (kind) => {
    const res = await fetch(`${API}/reports/export?kind=${kind}`, { headers: { Authorization: `Bearer ${getToken()}` } });
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = `${kind}_report.csv`; a.click();
  };

  if (!caller || !affiliate || !company) return <PageLoader />;

  return (
    <div data-testid="reports-page">
      <PageHeader title="Reports & Dashboards" subtitle="Computed aggregations · IST"
        actions={can("reports:export") && <Button variant="outline" onClick={() => exportCsv(tab)} data-testid="export-report-btn"><Download size={16} className="mr-1.5" /> Export {tab}</Button>} />

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="bg-slate-100">
          <TabsTrigger value="caller" data-testid="tab-caller">Caller</TabsTrigger>
          <TabsTrigger value="affiliate" data-testid="tab-affiliate">Affiliate</TabsTrigger>
          <TabsTrigger value="company" data-testid="tab-company">Company</TabsTrigger>
        </TabsList>

        <TabsContent value="caller" className="mt-4">
          <div className="mb-6 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
            <h3 className="mb-4 font-display text-base font-semibold text-slate-800">Calls by caller</h3>
            <div className="h-64">
              {caller.length === 0 ? (
                <div className="flex h-full items-center justify-center text-sm text-slate-400">No caller data in scope</div>
              ) : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={caller}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                  <XAxis dataKey="name" stroke="#94a3b8" fontSize={12} tickLine={false} />
                  <YAxis stroke="#94a3b8" fontSize={12} tickLine={false} axisLine={false} allowDecimals={false} />
                  <Tooltip contentStyle={{ borderRadius: 8, border: "1px solid #e2e8f0" }} />
                  <Bar dataKey="calls" fill="#0EA5E9" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="conversions" fill="#0369A1" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
              )}
            </div>
          </div>
          <ReportTable rows={caller} cols={[["name", "Caller"], ["calls", "Calls"], ["connected", "Connected"], ["leads", "Leads"], ["conversions", "Conversions"], ["conversion_rate", "Conv %"]]} testid="caller-table" />
        </TabsContent>

        <TabsContent value="affiliate" className="mt-4">
          <ReportTable rows={affiliate} money={["total_balance"]} cols={[["name", "Affiliate"], ["clients", "Clients"], ["ftd", "FTD"], ["total_balance", "Total Balance"]]} testid="affiliate-table" />
        </TabsContent>

        <TabsContent value="company" className="mt-4">
          <ReportTable rows={company} cols={[["source", "Source"], ["leads", "Leads"], ["conversions", "Conversions"], ["conversion_rate", "Conv %"]]} testid="company-table" />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function ReportTable({ rows, cols, money = [], testid }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white shadow-sm" data-testid={testid}>
      <Table>
        <TableHeader>
          <TableRow className="bg-slate-50">{cols.map(([k, l]) => <TableHead key={k}>{l}</TableHead>)}</TableRow>
        </TableHeader>
        <TableBody>
          {rows.length === 0 ? (
            <TableRow><TableCell colSpan={cols.length} className="py-8 text-center text-slate-400">No data</TableCell></TableRow>
          ) : rows.map((r, i) => (
            <TableRow key={i}>
              {cols.map(([k]) => (
                <TableCell key={k} className={k === cols[0][0] ? "font-medium text-slate-800" : "tabular text-slate-600"}>
                  {money.includes(k) ? <Money value={r[k]} /> : k === "conversion_rate" ? <StatusPill color="sky">{r[k]}%</StatusPill> : r[k]}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
