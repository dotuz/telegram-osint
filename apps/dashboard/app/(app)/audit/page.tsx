"use client";

import { api } from "@/lib/api";
import { PageTitle, State, useAsync } from "@/components/ui";

export default function AuditPage() {
  const { data, error, loading } = useAsync(() => api.audit(200));
  return (
    <div>
      <PageTitle>Audit log</PageTitle>
      <State loading={loading} error={error} />
      {data && (
        <div className="card overflow-x-auto">
          <table className="data">
            <thead>
              <tr>
                <th>Time</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Resource</th>
                <th>Result</th>
              </tr>
            </thead>
            <tbody>
              {data.audit.map((a) => (
                <tr key={a.id}>
                  <td className="text-muted">{a.created_at?.slice(0, 19).replace("T", " ")}</td>
                  <td className="font-mono text-xs">{a.actor}</td>
                  <td>{a.action}</td>
                  <td className="text-muted">{a.resource ?? "—"}</td>
                  <td className={a.result === "denied" ? "text-red-400" : ""}>{a.result}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
