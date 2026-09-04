"use client";

import { useEffect, useState } from "react";
import { ApiError } from "@/lib/api";

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    fn()
      .then((d) => alive && (setData(d), setError(null)))
      .catch((e) => alive && setError(e instanceof ApiError ? e.message : String(e)))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  return { data, error, loading, reload: () => setNonce((n) => n + 1) };
}

export function PageTitle({ children, action }: { children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="mb-4 flex items-center justify-between">
      <h1 className="text-lg font-semibold">{children}</h1>
      {action}
    </div>
  );
}

export function State({ loading, error }: { loading: boolean; error: string | null }) {
  if (error) return <div className="card text-sm text-red-400">Error: {error}</div>;
  if (loading) return <div className="card text-sm text-muted">Loading…</div>;
  return null;
}

const TAG: Record<string, string> = {
  FACT: "bg-green-700 text-white",
  INFERENCE: "bg-yellow-700 text-white",
  UNKNOWN: "bg-slate-600 text-white",
  COMPLETED: "bg-green-700 text-white",
  RUNNING: "bg-blue-700 text-white",
  PENDING: "bg-slate-600 text-white",
  FAILED: "bg-red-700 text-white",
  CANCELLED: "bg-slate-700 text-white",
};

export function Tag({ value }: { value: string }) {
  return <span className={`tag ${TAG[value] ?? "bg-slate-700 text-white"}`}>{value}</span>;
}
