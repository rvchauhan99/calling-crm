import { useEffect, useState, useCallback } from "react"
import api, { formatApiError } from "@/lib/api"
import { useAuth } from "@/context/AuthContext"
import { PageHeader, EmptyState, PageLoader, StatusPill } from "@/components/common"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog"
import { SearchableSelect } from "@/components/ui/searchable-select"
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table"
import { toast } from "sonner"
import { Plus, Table as TableIcon, Pencil, Trash2, RefreshCw, Eye, Columns3 } from "lucide-react"
import { LEAD_SOURCES } from "@/constants/leadSources"
import {
  COLUMN_MAP_FIELDS,
  defaultColumnMap,
} from "@/constants/sheetColumnMaps"

const EXAMPLE_URL =
  "https://docs.google.com/spreadsheets/d/1aLEV8ZK1RkMaPzsaahfUZQ-zXKHFDSQLirF4Jbx-u0A/edit?gid=0#gid=0"

const empty = {
  name: "",
  sheet_url: "",
  enabled: true,
  auto_assign: false,
  source: "Facebook Ads",
  preset: "meta_lead_ads",
  poll_seconds: 120,
  column_map: defaultColumnMap("meta_lead_ads"),
}

const formatResult = (r) => {
  if (!r) return "—"
  return `+${r.created || 0} · dup ${r.duplicates || 0} · inv ${r.invalid || 0}` +
    (r.assigned ? ` · asg ${r.assigned}` : "")
}

const noneOption = { value: "", label: "(none)" }

export default function SheetSources() {
  const { can } = useAuth()
  const [list, setList] = useState(null)
  const [show, setShow] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState(empty)
  const [headers, setHeaders] = useState([])
  const [loadingColumns, setLoadingColumns] = useState(false)
  const [draftPreview, setDraftPreview] = useState(null)
  const [syncingId, setSyncingId] = useState(null)
  const [preview, setPreview] = useState(null)
  const [previewOpen, setPreviewOpen] = useState(false)

  const load = useCallback(async () => {
    const { data } = await api.get("/sheet-sources")
    setList(data.sheet_sources)
  }, [])
  useEffect(() => { load().catch(() => {}) }, [load])

  const openNew = () => {
    setEditing(null)
    setForm({ ...empty, column_map: defaultColumnMap("meta_lead_ads") })
    setHeaders([])
    setDraftPreview(null)
    setShow(true)
  }

  const openEdit = (s) => {
    setEditing(s)
    setForm({
      name: s.name || "",
      sheet_url: s.sheet_url || "",
      enabled: Boolean(s.enabled),
      auto_assign: Boolean(s.auto_assign),
      source: s.source || "Facebook Ads",
      preset: s.preset || "meta_lead_ads",
      poll_seconds: s.poll_seconds || 120,
      column_map: s.column_map
        ? { ...defaultColumnMap(s.preset || "meta_lead_ads"), ...s.column_map }
        : defaultColumnMap(s.preset || "meta_lead_ads"),
    })
    setHeaders([])
    setDraftPreview(null)
    setShow(true)
  }

  const handlePresetChange = (preset) => {
    setForm((f) => ({
      ...f,
      preset,
      column_map: defaultColumnMap(preset),
    }))
    setDraftPreview(null)
  }

  const handleMapChange = (key, value) => {
    setForm((f) => ({
      ...f,
      column_map: { ...f.column_map, [key]: value },
    }))
    setDraftPreview(null)
  }

  const handleLoadColumns = async () => {
    if (!form.sheet_url.trim()) {
      toast.error("Enter a Google Sheet URL first")
      return
    }
    setLoadingColumns(true)
    try {
      const { data } = await api.post("/sheet-sources/inspect", {
        sheet_url: form.sheet_url,
        preset: form.preset,
      })
      setHeaders(data.headers || [])
      if (data.suggested_map) {
        setForm((f) => ({ ...f, column_map: { ...f.column_map, ...data.suggested_map } }))
      }
      toast.success(`Loaded ${(data.headers || []).length} columns`)
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail))
    } finally {
      setLoadingColumns(false)
    }
  }

  const handleDraftPreview = async () => {
    if (!form.sheet_url.trim()) {
      toast.error("Enter a Google Sheet URL first")
      return
    }
    if (!form.column_map?.name || !form.column_map?.phone) {
      toast.error("Map Name and Phone columns first")
      return
    }
    try {
      const { data } = await api.post("/sheet-sources/preview-draft", {
        sheet_url: form.sheet_url,
        preset: form.preset,
        column_map: form.column_map,
      })
      setDraftPreview(data)
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail))
    }
  }

  const save = async () => {
    if (!form.column_map?.name || !form.column_map?.phone) {
      toast.error("Name and Phone column mapping are required")
      return
    }
    try {
      const payload = {
        ...form,
        poll_seconds: Number(form.poll_seconds) || 120,
        column_map: form.column_map,
      }
      if (editing) await api.put(`/sheet-sources/${editing.id}`, payload)
      else await api.post("/sheet-sources", payload)
      toast.success("Saved")
      setShow(false)
      load()
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail))
    }
  }

  const remove = async (id) => {
    if (!window.confirm("Delete this sheet source?")) return
    try {
      await api.delete(`/sheet-sources/${id}`)
      toast.success("Deleted")
      load()
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail))
    }
  }

  const handleSync = async (id) => {
    setSyncingId(id)
    try {
      const { data } = await api.post(`/sheet-sources/${id}/sync`)
      if (data.status === "error") {
        toast.error(data.error || "Sync failed")
      } else if (data.status === "skipped") {
        toast.message(data.error || "Sync skipped")
      } else {
        toast.success(
          `Synced: ${data.created} created, ${data.duplicates} duplicates` +
          (data.assigned ? `, ${data.assigned} assigned` : "")
        )
      }
      load()
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail))
    } finally {
      setSyncingId(null)
    }
  }

  const handlePreview = async (id) => {
    try {
      const { data } = await api.get(`/sheet-sources/${id}/preview`)
      setPreview(data)
      setPreviewOpen(true)
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail))
    }
  }

  const headerOptions = [
    noneOption,
    ...headers.map((h) => ({ value: h, label: h })),
  ]
  // When editing without loaded headers, still show current map values as options
  const mapSelectOptions = (currentVal) => {
    const opts = [...headerOptions]
    if (currentVal && !opts.some((o) => o.value === currentVal)) {
      opts.push({ value: currentVal, label: currentVal })
    }
    return opts
  }

  if (!list) return <PageLoader />

  return (
    <div data-testid="sheet-sources-page">
      <PageHeader
        title="Sheet Sources"
        subtitle="Auto-capture leads from Google Sheets · column mapping master"
        actions={can("sheet_sources:create") && (
          <Button
            className="bg-sky-500 hover:bg-sky-600"
            onClick={openNew}
            data-testid="new-sheet-source-btn"
          >
            <Plus size={16} className="mr-1.5" /> New Sheet Source
          </Button>
        )}
      />

      <div className="rounded-lg border border-slate-200 bg-white shadow-sm">
        {list.length === 0 ? (
          <EmptyState
            icon={TableIcon}
            title="No sheet sources"
            description={`Add a Google Sheet URL (shared as Anyone with the link). Example Meta Lead Ads sheet: ${EXAMPLE_URL}`}
            testid="sheet-sources-empty"
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="bg-slate-50">
                <TableHead>Name</TableHead>
                <TableHead>CRM Source</TableHead>
                <TableHead>Enabled</TableHead>
                <TableHead>Auto-assign</TableHead>
                <TableHead>Last sync</TableHead>
                <TableHead>Result</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {list.map((s) => (
                <TableRow key={s.id} data-testid={`sheet-source-row-${s.id}`}>
                  <TableCell className="font-medium">
                    <div>{s.name}</div>
                    <div className="mt-0.5 max-w-xs truncate text-xs text-slate-400" title={s.sheet_url}>
                      {s.sheet_url}
                    </div>
                    {s.last_error && (
                      <p className="mt-1 text-xs text-red-500" data-testid={`sheet-error-${s.id}`}>
                        {s.last_error}
                      </p>
                    )}
                  </TableCell>
                  <TableCell>
                    <StatusPill color="sky">{s.source}</StatusPill>
                  </TableCell>
                  <TableCell>
                    {s.enabled
                      ? <StatusPill color="sky">On</StatusPill>
                      : <StatusPill color="slate">Off</StatusPill>}
                  </TableCell>
                  <TableCell>
                    {s.auto_assign
                      ? <StatusPill color="amber">Quota</StatusPill>
                      : <span className="text-slate-300">Off</span>}
                  </TableCell>
                  <TableCell className="text-sm text-slate-500">
                    {s.last_synced_at
                      ? new Date(s.last_synced_at).toLocaleString()
                      : "Never"}
                    {s.last_status && s.last_status !== "never" && (
                      <span className="ml-1 text-xs">({s.last_status})</span>
                    )}
                  </TableCell>
                  <TableCell className="tabular text-sm text-slate-600">
                    {formatResult(s.last_result)}
                  </TableCell>
                  <TableCell className="text-right">
                    {can("sheet_sources:view") && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handlePreview(s.id)}
                        aria-label="Preview sheet"
                        data-testid={`preview-sheet-${s.id}`}
                      >
                        <Eye size={15} />
                      </Button>
                    )}
                    {can("sheet_sources:sync") && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleSync(s.id)}
                        disabled={syncingId === s.id}
                        aria-label="Sync now"
                        data-testid={`sync-sheet-${s.id}`}
                      >
                        <RefreshCw size={15} className={syncingId === s.id ? "animate-spin" : ""} />
                      </Button>
                    )}
                    {can("sheet_sources:edit") && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => openEdit(s)}
                        data-testid={`edit-sheet-${s.id}`}
                      >
                        <Pencil size={15} />
                      </Button>
                    )}
                    {can("sheet_sources:delete") && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => remove(s.id)}
                        data-testid={`del-sheet-${s.id}`}
                      >
                        <Trash2 size={15} className="text-red-500" />
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>

      <Dialog open={show} onOpenChange={setShow}>
        <DialogContent className="bg-white max-w-2xl max-h-[90vh] overflow-y-auto" data-testid="sheet-source-dialog">
          <DialogHeader>
            <DialogTitle>{editing ? "Edit" : "New"} Sheet Source</DialogTitle>
            <DialogDescription>
              Sheet must be shared as Anyone with the link can view.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label>Name</Label>
              <Input
                value={form.name}
                className="mt-1 focus-visible:ring-sky-500"
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                data-testid="sheet-source-name"
                aria-label="Sheet source name"
              />
            </div>
            <div>
              <Label>Google Sheet URL</Label>
              <Input
                value={form.sheet_url}
                className="mt-1 focus-visible:ring-sky-500"
                placeholder="https://docs.google.com/spreadsheets/d/..."
                onChange={(e) => setForm({ ...form, sheet_url: e.target.value })}
                data-testid="sheet-source-url"
                aria-label="Google Sheet URL"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <SearchableSelect
                  value={form.preset}
                  onChange={handlePresetChange}
                  options={[
                    { value: "meta_lead_ads", label: "Meta Lead Ads" },
                    { value: "generic", label: "Generic (name/phone/email)" },
                  ]}
                  placeholder="Preset"
                  searchPlaceholder="Search preset…"
                  label="Column preset"
                  testId="sheet-source-preset"
                />
              </div>
              <div>
                <SearchableSelect
                  value={form.source}
                  onChange={(v) => setForm({ ...form, source: v })}
                  options={LEAD_SOURCES.map((s) => ({ value: s, label: s }))}
                  placeholder="CRM source"
                  searchPlaceholder="Search source…"
                  label="CRM lead source"
                  testId="sheet-source-crm-source"
                />
              </div>
            </div>

            <div className="rounded-md border border-slate-200 p-3 space-y-3" data-testid="sheet-column-mapping">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p className="text-sm font-medium">Column mapping</p>
                  <p className="text-xs text-slate-400">
                    Preset fills defaults; change only if your headers differ.
                  </p>
                </div>
                <div className="flex gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={handleLoadColumns}
                    disabled={loadingColumns}
                    data-testid="sheet-load-columns"
                    aria-label="Load columns from sheet"
                  >
                    <Columns3 size={14} className="mr-1.5" />
                    {loadingColumns ? "Loading…" : "Load columns"}
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={handleDraftPreview}
                    data-testid="sheet-draft-preview"
                    aria-label="Preview mapped rows"
                  >
                    <Eye size={14} className="mr-1.5" />
                    Preview
                  </Button>
                </div>
              </div>
              {headers.length > 0 && (
                <p className="text-xs text-slate-500" data-testid="sheet-headers-count">
                  {headers.length} columns detected
                </p>
              )}
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {COLUMN_MAP_FIELDS.map((field) => (
                  <SearchableSelect
                    key={field.key}
                    value={form.column_map?.[field.key] ?? ""}
                    onChange={(v) => handleMapChange(field.key, v)}
                    options={
                      field.required
                        ? mapSelectOptions(form.column_map?.[field.key]).filter((o) => o.value !== "")
                        : mapSelectOptions(form.column_map?.[field.key])
                    }
                    placeholder={field.required ? "Select column…" : "(none)"}
                    searchPlaceholder="Search columns…"
                    label={`${field.label}${field.required ? " *" : ""}`}
                    testId={field.testId}
                  />
                ))}
              </div>
              {draftPreview && (
                <div className="max-h-40 overflow-auto rounded border border-slate-100 p-2 text-xs" data-testid="sheet-draft-preview-table">
                  {(draftPreview.rows || []).length === 0 ? (
                    <p className="text-slate-500">No mappable rows with this map</p>
                  ) : (
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Name</TableHead>
                          <TableHead>Phone</TableHead>
                          <TableHead>Email</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {draftPreview.rows.map((r, i) => (
                          <TableRow key={i}>
                            <TableCell>{r.name}</TableCell>
                            <TableCell className="tabular">{r.phone}</TableCell>
                            <TableCell>{r.email || "—"}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  )}
                </div>
              )}
            </div>

            <div>
              <Label>Poll interval (seconds, min 60)</Label>
              <Input
                type="number"
                min={60}
                value={form.poll_seconds}
                className="mt-1 focus-visible:ring-sky-500"
                onChange={(e) => setForm({ ...form, poll_seconds: Number(e.target.value) })}
                data-testid="sheet-source-poll"
                aria-label="Poll interval seconds"
              />
            </div>
            <div className="flex items-center justify-between rounded-md border border-slate-200 p-3">
              <div>
                <p className="text-sm font-medium">Enabled</p>
                <p className="text-xs text-slate-400">Background poll when enabled</p>
              </div>
              <Switch
                checked={form.enabled}
                onCheckedChange={(v) => setForm({ ...form, enabled: v })}
                data-testid="sheet-source-enabled"
              />
            </div>
            <div className="flex items-center justify-between rounded-md border border-slate-200 p-3">
              <div>
                <p className="text-sm font-medium">Auto-assign</p>
                <p className="text-xs text-slate-400">
                  Assign new leads by caller daily quota; otherwise leave unassigned
                </p>
              </div>
              <Switch
                checked={form.auto_assign}
                onCheckedChange={(v) => setForm({ ...form, auto_assign: v })}
                data-testid="sheet-source-auto-assign"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShow(false)}>Cancel</Button>
            <Button
              className="bg-sky-500 hover:bg-sky-600"
              onClick={save}
              data-testid="save-sheet-source-btn"
            >
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={previewOpen} onOpenChange={setPreviewOpen}>
        <DialogContent className="bg-white max-w-2xl" data-testid="sheet-preview-dialog">
          <DialogHeader>
            <DialogTitle>Sheet preview</DialogTitle>
            <DialogDescription>First mapped rows (no inserts)</DialogDescription>
          </DialogHeader>
          {preview && (
            <div className="max-h-80 space-y-2 overflow-auto text-sm">
              <p className="text-xs text-slate-400">
                Headers: {(preview.headers || []).join(", ") || "—"}
              </p>
              {(preview.rows || []).length === 0 ? (
                <p className="text-slate-500">No mappable rows in scan</p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Name</TableHead>
                      <TableHead>Phone</TableHead>
                      <TableHead>Email</TableHead>
                      <TableHead>External ID</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {preview.rows.map((r, i) => (
                      <TableRow key={i}>
                        <TableCell>{r.name}</TableCell>
                        <TableCell className="tabular">{r.phone}</TableCell>
                        <TableCell>{r.email || "—"}</TableCell>
                        <TableCell className="text-xs">{r.external_id || "—"}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setPreviewOpen(false)}>Close</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
