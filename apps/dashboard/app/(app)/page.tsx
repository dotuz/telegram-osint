"use client";

import { api } from "@/lib/api";
import { PageTitle, State, useAsync } from "@/components/ui";

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="card">
      <div className="text-2xl font-semibold">{value}</div>
      <div className="text-xs text-muted">{label}</div>
    </div>
  );
}

export default function Overview() {
  const { data, error, loading } = useAsync(() => api.stats());
  const { data: health } = useAsync(() => api.sourcesHealth());

  return (
    <div>
      <PageTitle>Overview</PageTitle>
      <State loading={loading} error={error} />
      {data && (
        <>
          <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="My targets" value={data.me?.targets ?? 0} />
            <Stat label="My searches" value={data.me?.searches ?? 0} />
            <Stat label="My reports" value={data.me?.reports ?? 0} />
            <Stat label="Active watches" value={data.me?.watches ?? 0} />
          </div>
          <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Telegram accounts" value={data.graph?.telegram_accounts ?? 0} />
            <Stat label="IOCs" value={data.graph?.iocs ?? 0} />
            <Stat label="Relationships" value={data.graph?.relationships ?? 0} />
            <Stat label="Evidence rows" value={data.graph?.evidence ?? 0} />
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <div className="card">
              <div className="mb-2 text-sm font-medium">Jobs by state</div>
              {Object.entries(data.jobs_by_state ?? {}).map(([k, v]) => (
                <div key={k} className="flex justify-between text-sm">
                  <span className="text-muted">{k}</span>
                  <span>{v as number}</span>
                </div>
              ))}
            </div>
            <div className="card">
              <div className="mb-2 text-sm font-medium">Sources</div>
              {(health?.sources ?? []).map((s: any) => (
                <div key={s.name} className="flex justify-between text-sm">
                  <span className="text-muted">{s.name}</span>
                  <span className={s.healthy ? "text-green-400" : "text-red-400"}>
                    {s.healthy ? "healthy" : "down"}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
