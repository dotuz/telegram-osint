"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { PageTitle } from "@/components/ui";

type Mode = "user" | "messages" | "username";

export default function SearchPage() {
  const [mode, setMode] = useState<Mode>("user");
  const [q, setQ] = useState("");
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const r =
        mode === "user"
          ? await api.searchUser(q)
          : mode === "messages"
            ? await api.searchMessages(q)
            : await api.usernameOsint(q);
      setResult(r);
    } catch (err: any) {
      setError(err.message ?? "search failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <PageTitle>Search</PageTitle>
      <form onSubmit={run} className="mb-4 flex flex-wrap gap-2">
        <select
          className="input max-w-[10rem]"
          value={mode}
          onChange={(e) => setMode(e.target.value as Mode)}
        >
          <option value="user">Telegram user</option>
          <option value="messages">Public messages</option>
          <option value="username">Username OSINT</option>
        </select>
        <input
          className="input max-w-sm"
          placeholder={mode === "messages" ? "search terms" : "@handle"}
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <button className="btn-primary" disabled={busy || !q.trim()}>
          {busy ? "…" : "Search"}
        </button>
      </form>

      {error && <div className="card text-sm text-red-400">{error}</div>}
      {result && (
        <div className="card">
          <pre className="overflow-x-auto text-xs">{JSON.stringify(result, null, 2)}</pre>
        </div>
      )}
    </div>
  );
}
