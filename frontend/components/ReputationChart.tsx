"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import type { BacktestResponse } from "@/lib/types";

interface Props {
  result: BacktestResponse;
}

const TICKER_COLORS = [
  "#3B82F6",
  "#10B981",
  "#F59E0B",
  "#8B5CF6",
  "#EF4444",
  "#06B6D4",
  "#EC4899",
  "#F97316",
];

interface TooltipPayloadItem {
  name: string;
  value: number;
}

interface CustomTooltipProps {
  active?: boolean;
  payload?: TooltipPayloadItem[];
  label?: string;
}

function CustomTooltip({ active, payload, label }: CustomTooltipProps) {
  if (!active || !payload?.length) return null;
  const val = payload[0].value as number;
  return (
    <div
      className="rounded-lg border px-3 py-2 text-sm font-mono"
      style={{
        background: "var(--color-surface)",
        borderColor: "var(--color-border)",
        color: "var(--color-text)",
      }}
    >
      <p className="font-semibold">{label}</p>
      <p style={{ color: "var(--color-secondary)" }}>Accuracy: {(val * 100).toFixed(1)}%</p>
    </div>
  );
}

export default function ReputationChart({ result }: Props) {
  const { per_ticker, total, correct, accuracy } = result;

  const chartData = Object.entries(per_ticker).map(([ticker, stats]) => ({
    ticker,
    accuracy: stats.accuracy,
    total: stats.total,
    correct: stats.correct,
  }));

  return (
    <div className="space-y-4">
      {/* Summary KPIs */}
      <div className="grid grid-cols-3 gap-3">
        <KpiCard label="Total Runs" value={String(total)} />
        <KpiCard label="Correct" value={String(correct)} accent="#10B981" />
        <KpiCard
          label="Overall Accuracy"
          value={`${(accuracy * 100).toFixed(1)}%`}
          accent={accuracy >= 0.5 ? "#10B981" : "#EF4444"}
        />
      </div>

      {/* Per-ticker bar chart */}
      {chartData.length > 0 && (
        <div
          className="rounded-lg border p-5"
          style={{ background: "var(--color-surface)", borderColor: "var(--color-border)" }}
        >
          <h3
            className="text-xs font-mono uppercase tracking-widest mb-4"
            style={{ color: "var(--color-muted)" }}
          >
            Accuracy by Ticker
          </h3>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={chartData} margin={{ top: 4, right: 8, left: -16, bottom: 4 }}>
              <XAxis
                dataKey="ticker"
                tick={{ fill: "#94A3B8", fontFamily: "Fira Code, monospace", fontSize: 12 }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
                tick={{ fill: "#94A3B8", fontFamily: "Fira Code, monospace", fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                domain={[0, 1]}
              />
              <Tooltip content={<CustomTooltip />} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
              <Bar dataKey="accuracy" radius={[4, 4, 0, 0]}>
                {chartData.map((_, index) => (
                  <Cell
                    key={`cell-${index}`}
                    fill={TICKER_COLORS[index % TICKER_COLORS.length]}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Per-ticker table */}
      {chartData.length > 0 && (
        <div
          className="rounded-lg border overflow-hidden"
          style={{ background: "var(--color-surface)", borderColor: "var(--color-border)" }}
        >
          <table className="w-full text-sm">
            <thead>
              <tr style={{ borderBottom: `1px solid var(--color-border)` }}>
                <th className="text-left px-4 py-3 font-mono text-xs uppercase tracking-widest" style={{ color: "var(--color-muted)" }}>Ticker</th>
                <th className="text-right px-4 py-3 font-mono text-xs uppercase tracking-widest" style={{ color: "var(--color-muted)" }}>Total</th>
                <th className="text-right px-4 py-3 font-mono text-xs uppercase tracking-widest" style={{ color: "var(--color-muted)" }}>Correct</th>
                <th className="text-right px-4 py-3 font-mono text-xs uppercase tracking-widest" style={{ color: "var(--color-muted)" }}>Accuracy</th>
              </tr>
            </thead>
            <tbody>
              {chartData.map((row, i) => (
                <tr
                  key={row.ticker}
                  className="transition-colors duration-150 hover:bg-white/5"
                  style={{ borderBottom: i < chartData.length - 1 ? `1px solid var(--color-border)` : "none" }}
                >
                  <td className="px-4 py-3 font-mono font-semibold" style={{ color: TICKER_COLORS[i % TICKER_COLORS.length] }}>
                    {row.ticker}
                  </td>
                  <td className="px-4 py-3 text-right font-mono" style={{ color: "var(--color-text)" }}>{row.total}</td>
                  <td className="px-4 py-3 text-right font-mono" style={{ color: "#10B981" }}>{row.correct}</td>
                  <td className="px-4 py-3 text-right font-mono">
                    <span
                      style={{ color: row.accuracy >= 0.5 ? "#10B981" : "#EF4444" }}
                    >
                      {(row.accuracy * 100).toFixed(1)}%
                    </span>
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

function KpiCard({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent?: string;
}) {
  return (
    <div
      className="rounded-lg border p-4"
      style={{ background: "var(--color-surface)", borderColor: "var(--color-border)" }}
    >
      <p className="text-xs font-mono uppercase tracking-widest mb-1" style={{ color: "var(--color-muted)" }}>
        {label}
      </p>
      <p className="text-2xl font-mono font-bold" style={{ color: accent ?? "var(--color-text)" }}>
        {value}
      </p>
    </div>
  );
}
