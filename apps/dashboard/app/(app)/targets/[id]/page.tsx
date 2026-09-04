"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import { PageTitle, State, useAsync } from "@/components/ui";
import { Graph } from "@/components/Graph";

type Tab = "overview" | "graph" | "timeline";

export default function TargetDetail() {
  const { id } = useParams<{ id: string }>();
  const [tab, setTab] = useState<Tab>("overview");
  const target = useAsync(() => api.target(id), [id]);
  const graph = useAsync(() => api.targetGraph(id, 2), [id]);
  const timeline = useAsync(() => api.targetTimeline(id), [id]);

  async function makeReport() {
    if (!target.data) return;
    await api.createReport(target.data.value);
    alert("Report generated — see Reports.");
  }

  return (
    <div>
      <PageTitle
        action={
          <button className="btn-primary" onClick={makeReport}>
            Generate report
          </button>
        }
      >
        {target.data?.value ?? "Target"}
      </PageTitle>

      <div className="mb-4 flex gap-2">
        {(["overview", "graph", "timeline"] as Tab[]).map((t) => (
          <button
            key={t}
            className={`btn ${tab === t ? "border-accent text-white" : ""}`}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === "overview" && (
        <>
          <State loading={target.loading} error={target.error} />
          {target.data && (
            <div className="card">
              <div className="text-sm text-muted">Resolved entities</div>
              <ul className="mt-2 space-y-1 text-sm">
                {(target.data.resolved_entities ?? []).map((e) => (
                  <li key={e} className="font-mono text-xs">
                    {e}
                  </li>
                ))}
                {(target.data.resolved_entities ?? []).length === 0 && (
                  <li className="text-muted">Nothing resolved yet.</li>
                )}
              </ul>
            </div>
          )}
        </>
      )}

      {tab === "graph" && (
        <>
          <State loading={graph.loading} error={graph.error} />
          {graph.data && <Graph view={graph.data} />}
        </>
      )}

      {tab === "timeline" && (
        <>
          <State loading={timeline.loading} error={timeline.error} />
          {timeline.data &&
            Object.entries(timeline.data.by_year)
              .sort()
              .map(([year, events]) => (
                <div key={year} className="card mb-3">
                  <div className="mb-2 font-medium">{year}</div>
                  <ul className="space-y-1 text-sm">
                    {events.map((ev, i) => (
                      <li key={i} className="flex gap-3">
                        <span className="font-mono text-xs text-muted">
                          {ev.when.slice(0, 10)}
                        </span>
                        <span>{ev.title}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
        </>
      )}
    </div>
  );
}
