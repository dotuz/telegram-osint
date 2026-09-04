"use client";

import { useAuth } from "@/lib/auth";
import { PageTitle } from "@/components/ui";

export default function SettingsPage() {
  const { user } = useAuth();
  return (
    <div>
      <PageTitle>Settings</PageTitle>
      <div className="card space-y-2 text-sm">
        <div>
          <span className="text-muted">Email: </span>
          {user?.email}
        </div>
        <div>
          <span className="text-muted">Role: </span>
          {user?.role}
        </div>
        <div>
          <span className="text-muted">User id: </span>
          <span className="font-mono text-xs">{user?.id}</span>
        </div>
      </div>
      <p className="mt-4 text-xs text-muted">
        Password changes, MFA, and API keys land in Phase 12. For now use{" "}
        <code>python -m apps.api set-password</code>.
      </p>
    </div>
  );
}
