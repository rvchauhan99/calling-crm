import { cn } from "@/lib/utils"

export function PanelHeader({ title, hint }) {
  return (
    <div className="mb-2 flex items-baseline justify-between gap-2">
      <h3 className="font-display text-sm font-semibold text-slate-800">{title}</h3>
      {hint && <span className="text-[10px] uppercase tracking-wide text-slate-400">{hint}</span>}
    </div>
  )
}

export function KpiCard({ label, value, hint, onClick, testId, accent = "sky" }) {
  const accents = {
    sky: "hover:border-sky-300",
    amber: "hover:border-amber-300",
    blue: "hover:border-blue-300",
    red: "hover:border-red-300",
  }
  return (
    <button
      type="button"
      data-testid={testId}
      onClick={onClick}
      className={cn(
        "rounded-lg border border-slate-200 bg-white p-3 text-left shadow-sm transition-colors",
        onClick ? cn("cursor-pointer", accents[accent]) : "cursor-default",
      )}
    >
      <p className="text-[10px] font-medium uppercase tracking-wider text-slate-500">{label}</p>
      <p className="mt-1 font-display text-xl font-bold tabular text-slate-900">{value}</p>
      {hint && <p className="mt-0.5 text-[11px] text-slate-400">{hint}</p>}
    </button>
  )
}

export function MiniBar({ label, count, max, onClick }) {
  const pct = max > 0 ? Math.round((count / max) * 100) : 0
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-2 py-1 text-left text-xs",
        onClick ? "cursor-pointer hover:bg-slate-50" : "cursor-default",
      )}
    >
      <span className="w-28 shrink-0 truncate text-slate-600">{label}</span>
      <div className="h-1.5 flex-1 rounded-full bg-slate-100">
        <div className="h-1.5 rounded-full bg-sky-500" style={{ width: `${pct}%` }} />
      </div>
      <span className="w-8 text-right tabular text-slate-700">{count}</span>
    </button>
  )
}

export function InsightCard({ severity, title, detail, onClick }) {
  const map = {
    critical: "border-red-200 bg-red-50 text-red-800",
    warning: "border-amber-200 bg-amber-50 text-amber-800",
    info: "border-sky-200 bg-sky-50 text-sky-800",
  }
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-md border px-3 py-2 text-left text-xs",
        map[severity] || map.info,
        onClick && "cursor-pointer hover:opacity-90",
      )}
    >
      <p className="font-semibold">{title}</p>
      <p className="mt-0.5 opacity-80">{detail}</p>
    </button>
  )
}

export function FilterChip({ label, onRemove }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2.5 py-0.5 text-xs text-slate-700">
      {label}
      <button
        type="button"
        aria-label={`Remove ${label}`}
        onClick={onRemove}
        className="ml-0.5 text-slate-400 hover:text-slate-700"
      >
        ×
      </button>
    </span>
  )
}

export function buildLeadHref(params = {}) {
  const p = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "" && v !== "all") p.set(k, String(v))
  })
  const qs = p.toString()
  return qs ? `/leads?${qs}` : "/leads"
}

export function monthStartISO(d = new Date()) {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, "0")
  return `${y}-${m}-01`
}

export function todayISO(d = new Date()) {
  return d.toISOString().slice(0, 10)
}

export function startOfWeekISO(d = new Date()) {
  const x = new Date(d)
  const day = x.getDay()
  const diff = day === 0 ? 6 : day - 1
  x.setDate(x.getDate() - diff)
  return todayISO(x)
}

export function monthsAgoISO(months, d = new Date()) {
  const x = new Date(d)
  x.setMonth(x.getMonth() - months)
  return todayISO(x)
}
