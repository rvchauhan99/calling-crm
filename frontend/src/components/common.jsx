import { cn } from "@/lib/utils";
import { Loader2 } from "lucide-react";

export function PageHeader({ title, subtitle, actions, testid }) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between mb-6" data-testid={testid}>
      <div>
        <h1 className="font-display text-2xl md:text-3xl font-bold text-slate-900">{title}</h1>
        {subtitle && <p className="text-sm text-slate-500 mt-1">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2 flex-wrap">{actions}</div>}
    </div>
  );
}

export function StatCard({ label, value, hint, icon: Icon, accent = "sky", testid }) {
  const accents = {
    sky: "bg-sky-50 text-sky-600",
    slate: "bg-slate-100 text-slate-600",
    amber: "bg-amber-50 text-amber-600",
    blue: "bg-blue-50 text-blue-600",
  };
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm hover:shadow-md transition-shadow duration-200" data-testid={testid}>
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs tracking-wider uppercase text-slate-500">{label}</p>
          <p className="mt-2 font-display text-2xl font-bold text-slate-900 tabular">{value}</p>
          {hint && <p className="mt-1 text-xs text-slate-400">{hint}</p>}
        </div>
        {Icon && (
          <span className={cn("flex h-10 w-10 items-center justify-center rounded-lg", accents[accent])}>
            <Icon size={20} strokeWidth={2} />
          </span>
        )}
      </div>
    </div>
  );
}

export function EmptyState({ icon: Icon, title, description, action, testid }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-slate-300 bg-slate-50/50 py-16 px-6 text-center" data-testid={testid}>
      {Icon && (
        <span className="mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-sky-50 text-sky-500">
          <Icon size={26} />
        </span>
      )}
      <h3 className="font-display text-lg font-semibold text-slate-800">{title}</h3>
      {description && <p className="mt-1 max-w-sm text-sm text-slate-500">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function Spinner({ className }) {
  return <Loader2 className={cn("animate-spin text-sky-500", className)} size={20} />;
}

export function PageLoader() {
  return (
    <div className="flex h-64 items-center justify-center">
      <Spinner className="h-7 w-7" />
    </div>
  );
}

export function TableSkeleton({ rows = 6 }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-11 w-full animate-pulse rounded bg-slate-100" />
      ))}
    </div>
  );
}

export function Money({ value, className }) {
  const n = Number(value || 0);
  return (
    <span className={cn("tabular", className)}>
      ₹{n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
    </span>
  );
}

export function StatusPill({ children, color = "sky" }) {
  const map = {
    sky: "bg-sky-50 text-sky-700 ring-sky-200",
    slate: "bg-slate-100 text-slate-600 ring-slate-200",
    amber: "bg-amber-50 text-amber-700 ring-amber-200",
    red: "bg-red-50 text-red-700 ring-red-200",
    blue: "bg-blue-50 text-blue-700 ring-blue-200",
  };
  return (
    <span className={cn("inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset", map[color])}>
      {children}
    </span>
  );
}
