"use client";

import { useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { PageTitle, State, useAsync } from "@/components/ui";

export default function TargetsPage() {
  const { data, error, loading, reload } = useAsync(() => api.targets());
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    if (!value.trim()) return;
    setBusy(true);
    try {
      await api.createTarget(value.trim());
      setValue("");
      reload();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <PageTitle>Targets</PageTitle>
      <form onSubmit={add} className="mb-4 flex gap-2">
        <input
          className="input max-w-xs"
          placeholder="@username or handle"
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
        <button className="btn-primary" disabled={busy}>
          Add & resolve
        </button>
      </form>
      <State loading={loading} error={error} />
      {data && (
        <div className="card overflow-x-auto">
          <table className="data">
            <thead>
              <tr>
                <th>Value</th>
                <th>Kind</th>
                <th>Label</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {data.targets.map((t) => (
                <tr key={t.id}>
                  <td>{t.value}</td>
                  <td className="text-muted">{t.kind}</td>
                  <td className="text-muted">{t.label ?? "—"}</td>
                  <td>
                    <Link className="text-accent" href={`/targets/${t.id}`}>
                      open →
                    </Link>
                  </td>
                </tr>
              ))}
              {data.targets.length === 0 && (
                <tr>
                  <td colSpan={4} className="text-muted">
                    No targets yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
