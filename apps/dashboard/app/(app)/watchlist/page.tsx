"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { PageTitle, State, useAsync } from "@/components/ui";

export default function WatchlistPage() {
  const { data, error, loading, reload } = useAsync(() => api.watchlist());
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    if (!value.trim()) return;
    setBusy(true);
    setMsg(null);
    try {
      await api.addWatch(value.trim());
      setValue("");
      reload();
    } catch (err: any) {
      setMsg(err.message ?? "failed");
    } finally {
      setBusy(false);
    }
  }

  async function poll(id: string) {
    const r = await api.pollWatch(id);
    setMsg(`${r.target}: ${r.activities.length} new event(s)`);
    reload();
  }

  return (
    <div>
      <PageTitle>Watchlist</PageTitle>
      <form onSubmit={add} className="mb-3 flex gap-2">
        <input
          className="input max-w-xs"
          placeholder="@username"
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
        <button className="btn-primary" disabled={busy}>
          Watch
        </button>
      </form>
      {msg && <div className="mb-3 text-sm text-muted">{msg}</div>}
      <State loading={loading} error={error} />
      {data && (
        <div className="card overflow-x-auto">
          <table className="data">
            <thead>
              <tr>
                <th>Handle</th>
                <th>Status</th>
                <th>Last checked</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {data.watchlist.map((w) => (
                <tr key={w.id}>
                  <td>{w.value}</td>
                  <td className={w.is_active ? "text-green-400" : "text-muted"}>
                    {w.is_active ? "active" : "paused"}
                  </td>
                  <td className="text-muted">{w.last_checked_at?.slice(0, 16) ?? "never"}</td>
                  <td className="space-x-2">
                    <button className="btn" onClick={() => poll(w.id)}>
                      poll
                    </button>
                    <button
                      className="btn"
                      onClick={async () => {
                        await api.removeWatch(w.value.replace(/^@/, ""));
                        reload();
                      }}
                    >
                      unwatch
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
