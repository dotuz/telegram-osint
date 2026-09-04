"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth";

const LINKS: [string, string][] = [
  ["/", "Overview"],
  ["/targets", "Targets"],
  ["/search", "Search"],
  ["/watchlist", "Watchlist"],
  ["/reports", "Reports"],
  ["/jobs", "Jobs"],
  ["/settings", "Settings"],
];

export function Nav() {
  const pathname = usePathname();
  const { user, logout } = useAuth();
  const links = user?.role === "ADMIN" ? [...LINKS, ["/audit", "Audit"] as [string, string]] : LINKS;

  return (
    <aside className="flex w-52 shrink-0 flex-col border-r border-border bg-panel p-3">
      <div className="mb-4 px-2 text-sm font-semibold">Telegram OSINT</div>
      <nav className="flex-1 space-y-1">
        {links.map(([href, label]) => {
          const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={`block rounded-md px-2 py-1.5 text-sm ${
                active ? "bg-accent/20 text-white" : "text-muted hover:text-slate-200"
              }`}
            >
              {label}
            </Link>
          );
        })}
      </nav>
      <div className="border-t border-border pt-3 text-xs text-muted">
        <div className="px-2">{user?.email}</div>
        <div className="px-2">{user?.role}</div>
        <button className="mt-2 btn w-full" onClick={logout}>
          Sign out
        </button>
      </div>
    </aside>
  );
}
