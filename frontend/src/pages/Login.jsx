import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/common";
import { PhoneOutgoing, ShieldCheck, BarChart3, Wallet } from "lucide-react";

const BG = "https://images.unsplash.com/photo-1707730318002-6fbd8ecd6b77?crop=entropy&cs=srgb&fm=jpg&ixid=M3w3NDk1ODF8MHwxfHNlYXJjaHwxfHxhYnN0cmFjdCUyMGdlb21ldHJpYyUyMHNreSUyMGJsdWV8ZW58MHx8fHwxNzg3ODM2NjA3fDA&ixlib=rb-4.1.0&q=85";

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError(""); setLoading(true);
    try {
      await login(email, password);
      navigate("/");
    } catch (err) {
      setError(formatApiError(err.response?.data?.detail) || err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen bg-white">
      <div className="flex w-full flex-col justify-center px-6 py-12 sm:px-12 lg:w-[46%] xl:px-20">
        <div className="mx-auto w-full max-w-sm">
          <div className="mb-8 flex items-center gap-2.5">
            <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-sky-500 text-white">
              <PhoneOutgoing size={21} />
            </span>
            <div className="leading-tight">
              <p className="font-display text-lg font-extrabold text-slate-900">CallingCRM</p>
              <p className="text-[11px] uppercase tracking-wider text-slate-400">Telecalling Suite</p>
            </div>
          </div>
          <h1 className="font-display text-3xl font-bold text-slate-900">Welcome back</h1>
          <p className="mt-2 text-sm text-slate-500">Sign in to your calling workspace.</p>

          <form onSubmit={submit} className="mt-8 space-y-4" data-testid="login-form">
            <div>
              <Label htmlFor="email">Email</Label>
              <Input id="email" type="email" value={email} data-testid="login-email"
                onChange={(e) => setEmail(e.target.value)} className="mt-1.5 focus-visible:ring-sky-500" required />
            </div>
            <div>
              <Label htmlFor="password">Password</Label>
              <Input id="password" type="password" value={password} data-testid="login-password"
                onChange={(e) => setPassword(e.target.value)} className="mt-1.5 focus-visible:ring-sky-500" required />
            </div>
            {error && <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-600" data-testid="login-error">{error}</p>}
            <Button type="submit" disabled={loading} data-testid="login-submit"
              className="w-full bg-sky-500 hover:bg-sky-600 text-white">
              {loading ? <Spinner className="text-white" /> : "Sign in"}
            </Button>
          </form>

          {process.env.NODE_ENV === "development" && (
            <div className="mt-8 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-500">
              <p className="font-semibold text-slate-600">Local setup</p>
              <p className="mt-1">Use the admin email/password from <code>backend/.env</code> (see README).</p>
              <p>Seeded demo users use <code>DEMO_PASSWORD</code> from the same file.</p>
            </div>
          )}
        </div>
      </div>

      <div className="relative hidden lg:block lg:w-[54%]">
        <img src={BG} alt="" className="absolute inset-0 h-full w-full object-cover" />
        <div className="absolute inset-0 bg-sky-900/55" />
        <div className="relative flex h-full flex-col justify-end p-14 text-white">
          <h2 className="font-display text-4xl font-bold leading-tight">The calling floor,<br />finally organized.</h2>
          <p className="mt-4 max-w-md text-sky-100">Granular RBAC, lead & client management, an append-only finance ledger, and computed analytics — in one clean workspace.</p>
          <div className="mt-8 flex gap-6">
            {[[ShieldCheck, "Deny-by-default RBAC"], [Wallet, "Append-only ledger"], [BarChart3, "Computed reports"]].map(([Icon, label]) => (
              <div key={label} className="flex items-center gap-2 text-sm text-sky-50">
                <Icon size={18} /> {label}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
