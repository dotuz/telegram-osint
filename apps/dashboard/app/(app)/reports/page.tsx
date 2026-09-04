"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { PageTitle, State, Tag, useAsync } from "@/components/ui";

export default function ReportsPage() {
  const { data, error, loading, reload } = useAsync(() => api.reports());
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    if (!value.trim()) return;
    setBusy(true);
    try {
      await api.createReport(value.trim());
      setValue("");
      reload();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <PageTitle>Reports</PageTitle>
      <form onSubmit={create} className="mb-4 flex gap-2">
        <input
          className="input max-w-xs"
          placeholder="@username"
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
        <button className="btn-primary" disabled={busy}>
          Generate
        </button>
      </form>
      <State loading={loading} error={error} />
      {data && (
        <div className="space-y-2">
          {data.reports.map((r) => (
            <div key={r.id} className="card flex items-center justify-between">
              <div>
                <div className="font-medium">{r.title}</div>
                <div className="text-xs text-muted">
                  {r.summary?.slice(0, 120) ?? "—"}
                </div>
              </div>
              <div className="flex items-center gap-3">
                <Tag value={r.status} />
                {Object.keys(r.artifacts).map((fmt) => (
                  <a
                    key={fmt}
                    className="text-accent text-sm"
                    href={api.reportDownloadUrl(r.id, fmt)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {fmt}
                  </a>
                ))}
              </div>
            </div>
          ))}
          {data.reports.length === 0 && (
            <div className="card text-sm text-muted">No reports yet.</div>
          )}
        </div>
      )}
    </div>
  );
}
