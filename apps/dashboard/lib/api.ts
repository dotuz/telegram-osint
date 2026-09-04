// Typed client for the Telegram OSINT API.
// Requests go through the Next.js /api/* rewrite to the backend.

const TOKEN_KEY = "toi.token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null) {
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* private mode */
  }
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(
  path: string,
  opts: { method?: string; body?: unknown; query?: Record<string, unknown> } = {},
): Promise<T> {
  const url = new URL(`/api/v1${path}`, window.location.origin);
  for (const [k, v] of Object.entries(opts.query ?? {})) {
    if (v !== undefined && v !== null) url.searchParams.set(k, String(v));
  }
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(url.toString(), {
    method: opts.method ?? "GET",
    headers,
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
    cache: "no-store",
  });

  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const data = text ? JSON.parse(text) : undefined;
  if (!res.ok) {
    const detail =
      (data && (data.detail || data.message)) || res.statusText || "request failed";
    throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data as T;
}

// ---- types -------------------------------------------------------------------

export interface Me {
  id: string;
  email: string;
  display_name: string | null;
  role: "USER" | "ANALYST" | "ADMIN";
}
export interface Target {
  id: string;
  kind: string;
  value: string;
  label: string | null;
  resolved_entities?: string[];
}
export interface GraphNode {
  id: string;
  type: string;
  label: string;
  attributes: Record<string, unknown>;
}
export interface GraphEdge {
  source: string;
  target: string;
  type: string;
  confidence: number;
}
export interface GraphView {
  root: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  truncated: boolean;
}
export interface TimelineEvent {
  when: string;
  year: number;
  kind: string;
  title: string;
  source: string | null;
}
export interface Job {
  id: string;
  kind: string;
  state: string;
  progress: number;
  retry_count: number;
  error: string | null;
  created_at: string | null;
}
export interface WatchRow {
  id: string;
  value: string;
  is_active: boolean;
  last_checked_at: string | null;
}
export interface ReportRow {
  id: string;
  title: string;
  status: string;
  summary: string | null;
  artifacts: Record<string, string>;
  generated_at: string | null;
}

// ---- endpoints --------------------------------------------------------------

export const api = {
  login: (email: string, password: string) =>
    request<{ access_token: string; user: Me; expires_in: number }>("/auth/login", {
      method: "POST",
      body: { email, password },
    }),
  me: () => request<Me>("/auth/me"),

  stats: () => request<Record<string, any>>("/stats"),
  audit: (limit = 100) => request<{ audit: any[] }>("/audit", { query: { limit } }),

  targets: () => request<{ targets: Target[] }>("/targets"),
  createTarget: (value: string, kind = "username") =>
    request<Target>("/targets", { method: "POST", body: { value, kind } }),
  target: (id: string) => request<Target>(`/targets/${id}`),
  targetGraph: (id: string, depth = 2) =>
    request<GraphView>(`/targets/${id}/graph`, { query: { depth } }),
  targetTimeline: (id: string) =>
    request<{ events: TimelineEvent[]; by_year: Record<string, TimelineEvent[]> }>(
      `/targets/${id}/timeline`,
    ),

  searchUser: (query: string) =>
    request<any>("/telegram/user", { method: "POST", body: { query } }),
  searchMessages: (query: string, limit = 25) =>
    request<any>("/telegram/messages", { method: "POST", body: { query, limit } }),
  usernameOsint: (username: string) =>
    request<any>("/username", { method: "POST", body: { username } }),
  searches: () => request<{ searches: any[] }>("/searches"),

  jobs: (limit = 25) => request<{ jobs: Job[] }>("/jobs", { query: { limit } }),
  job: (id: string) => request<Job>(`/jobs/${id}`),
  cancelJob: (id: string) => request<any>(`/jobs/${id}/cancel`, { method: "POST" }),

  watchlist: () => request<{ watchlist: WatchRow[] }>("/watchlist"),
  addWatch: (value: string) =>
    request<any>("/watchlist", { method: "POST", body: { value } }),
  removeWatch: (value: string) =>
    request<{ removed: boolean }>(`/watchlist/${encodeURIComponent(value)}`, {
      method: "DELETE",
    }),
  pollWatch: (id: string) => request<any>(`/watchlist/${id}/poll`, { method: "POST" }),

  reports: () => request<{ reports: ReportRow[] }>("/reports"),
  createReport: (value: string) =>
    request<any>("/reports", { method: "POST", body: { value } }),
  report: (id: string) => request<any>(`/reports/${id}`),
  reportDownloadUrl: (id: string, fmt: string) => `/api/v1/reports/${id}/download?fmt=${fmt}`,

  sourcesHealth: () => request<{ sources: any[] }>("/sources/health"),
};
