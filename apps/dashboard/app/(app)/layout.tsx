"use client";

import { Nav } from "@/components/Nav";
import { useRequireAuth } from "@/lib/auth";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { user, loading } = useRequireAuth();
  if (loading || !user) {
    return <div className="p-8 text-sm text-muted">Loading…</div>;
  }
  return (
    <div className="flex min-h-screen">
      <Nav />
      <main className="min-w-0 flex-1 p-6">{children}</main>
    </div>
  );
}
