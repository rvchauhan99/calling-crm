import { useEffect, useState, useCallback } from "react";
import api, { formatApiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { PageHeader, PageLoader, StatusPill } from "@/components/common";
import { toast } from "sonner";

const COLORS = {
  New: "sky", Contacted: "blue", Qualified: "sky", Proposal: "amber", Won: "blue", Lost: "slate",
};

export default function Pipeline() {
  const { can } = useAuth();
  const [data, setData] = useState(null);
  const [dragId, setDragId] = useState(null);

  const load = useCallback(async () => { const { data } = await api.get("/pipeline"); setData(data); }, []);
  useEffect(() => { load().catch(() => {}); }, [load]);

  const move = async (lid, stage) => {
    if (!can("pipeline:edit")) return;
    try {
      await api.put(`/pipeline/${lid}`, { stage });
      toast.success(`Moved to ${stage}`);
      load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  if (!data) return <PageLoader />;

  return (
    <div data-testid="pipeline-page">
      <PageHeader title="Pipeline" subtitle="Drag leads across deal stages" />
      <div className="flex gap-4 overflow-x-auto pb-4">
        {data.stages.map((stage) => {
          const items = data.board[stage] || [];
          return (
            <div key={stage} className="w-72 flex-shrink-0" data-testid={`stage-col-${stage}`}
              onDragOver={(e) => e.preventDefault()}
              onDrop={() => dragId && move(dragId, stage)}>
              <div className="mb-2 flex items-center justify-between rounded-md bg-white px-3 py-2 shadow-sm border border-slate-200">
                <span className="font-display text-sm font-semibold text-slate-700">{stage}</span>
                <StatusPill color={COLORS[stage]}>{items.length}</StatusPill>
              </div>
              <div className="space-y-2 min-h-[120px]">
                {items.map((l) => (
                  <div key={l.id} draggable={can("pipeline:edit")}
                    onDragStart={() => setDragId(l.id)} onDragEnd={() => setDragId(null)}
                    className="cursor-grab rounded-lg border border-slate-200 bg-white p-3 shadow-sm hover:shadow-md transition-shadow duration-200 active:cursor-grabbing"
                    data-testid={`pipeline-card-${l.id}`}>
                    <p className="font-medium text-sm text-slate-800">{l.name}</p>
                    <p className="tabular text-xs text-slate-500">{l.phone}</p>
                    <div className="mt-2 flex items-center justify-between">
                      <span className="text-[11px] text-slate-400">{l.source}</span>
                      {l.disposition_name && <span className="text-[11px] text-sky-600">{l.disposition_name}</span>}
                    </div>
                  </div>
                ))}
                {items.length === 0 && <div className="rounded-lg border border-dashed border-slate-200 py-6 text-center text-xs text-slate-300">Empty</div>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
