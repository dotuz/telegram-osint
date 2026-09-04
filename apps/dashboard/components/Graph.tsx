"use client";

import { useMemo } from "react";
import type { GraphView } from "@/lib/api";

const TYPE_COLOR: Record<string, string> = {
  target: "#4c8dff",
  telegram_account: "#39d98a",
  telegram_channel: "#f5a623",
  telegram_group: "#f5a623",
  username: "#b18cff",
  external_account: "#b18cff",
  domain: "#ff7ab6",
  url: "#ff7ab6",
  ip: "#ff7ab6",
  ioc: "#ff5c5c",
  message: "#8b95a5",
};

// Deterministic circular layout — no physics library, just enough to read the shape.
export function Graph({ view }: { view: GraphView }) {
  const layout = useMemo(() => {
    const W = 720;
    const H = 460;
    const cx = W / 2;
    const cy = H / 2;
    const nodes = view.nodes;
    const rootIdx = nodes.findIndex((n) => n.id === view.root);
    const positions = new Map<string, { x: number; y: number }>();
    nodes.forEach((n, i) => {
      if (i === rootIdx) {
        positions.set(n.id, { x: cx, y: cy });
        return;
      }
      const others = nodes.length - (rootIdx >= 0 ? 1 : 0);
      const k = i - (rootIdx >= 0 && i > rootIdx ? 1 : 0);
      const angle = (2 * Math.PI * k) / Math.max(1, others);
      const r = 170 + (k % 3) * 32;
      positions.set(n.id, { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) });
    });
    return { W, H, positions };
  }, [view]);

  return (
    <svg
      viewBox={`0 0 ${layout.W} ${layout.H}`}
      className="w-full rounded-lg border border-border bg-panel"
    >
      {view.edges.map((e, i) => {
        const a = layout.positions.get(e.source);
        const b = layout.positions.get(e.target);
        if (!a || !b) return null;
        return (
          <g key={i}>
            <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#2b3444" strokeWidth={1} />
            <text
              x={(a.x + b.x) / 2}
              y={(a.y + b.y) / 2}
              fill="#5b6675"
              fontSize={8}
              textAnchor="middle"
            >
              {e.type}
            </text>
          </g>
        );
      })}
      {view.nodes.map((n) => {
        const p = layout.positions.get(n.id);
        if (!p) return null;
        return (
          <g key={n.id}>
            <circle
              cx={p.x}
              cy={p.y}
              r={n.id === view.root ? 9 : 6}
              fill={TYPE_COLOR[n.type] ?? "#8b95a5"}
            />
            <text x={p.x + 10} y={p.y + 3} fill="#c9d1da" fontSize={9}>
              {n.label?.slice(0, 28)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
