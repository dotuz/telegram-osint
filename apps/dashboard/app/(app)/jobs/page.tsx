"use client";

import { useEffect } from "react";
import { api } from "@/lib/api";
import { PageTitle, State, Tag, useAsync } from "@/components/ui";

export default function JobsPage() {
  const { data, error, loading, reload } = useAsync(() => api.jobs(50));

  useEffect(() => {
    const t = setInterval(reload, 4000);
    return () => clearInterval(t);
  }, [reload]);

  return (
    <div>
      <PageTitle action={<button className="btn" onClick={reload}>refresh</button>}>Jobs</PageTitle>
      <State loading={loading} error={error} />
      {data && (
        <div className="card overflow-x-auto">
          <table className="data">
            <thead>
              <tr>
                <th>ID</th>
                <th>Kind</th>
                <th>State</th>
                <th>Progress</th>
                <th>Retries</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {data.jobs.map((j) => (
                <tr key={j.id}>
                  <td className="font-mono text-xs">{j.id.slice(0, 8)}</td>
                  <td>{j.kind}</td>
                  <td>
                    <Tag value={j.state} />
                  </td>
                  <td>{j.progress}%</td>
                  <td>{j.retry_count || "—"}</td>
                  <td>
                    {!["COMPLETED", "FAILED", "CANCELLED"].includes(j.state) && (
                      <button
                        className="btn"
                        onClick={async () => {
                          await api.cancelJob(j.id);
                          reload();
                        }}
                      >
                        cancel
                      </button>
                    )}
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
