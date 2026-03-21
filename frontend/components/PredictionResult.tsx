"use client";

import { TrendingUp, TrendingDown, Minus, AlertCircle } from "lucide-react";
import type { AnalyzeResponse, WeightedSignal } from "@/lib/types";

interface Props {
  result: AnalyzeResponse;
}

const AGENT_LABELS: Record<string, string> = {
  fundamentals: "Fundamentals",
  sentiment: "Sentiment",
  technical: "Technical",
  bull: "Bull Researcher",
  bear: "Bear Researcher",
};

function DirectionBadge({ direction }: { direction: "up" | "down" | "neutral" }) {
  if (direction === "up") {
    return (
      <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded text-sm font-semibold font-mono" style={{ background: "#064E3B", color: "#10B981" }}>
        <TrendingUp size={14} />
        UP
      </span>
    );
  }
  if (direction === "down") {
    return (
      <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded text-sm font-semibold font-mono" style={{ background: "#450A0A", color: "#EF4444" }}>
        <TrendingDown size={14} />
        DOWN
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded text-sm font-semibold font-mono" style={{ background: "#1E293B", color: "#94A3B8" }}>
      <Minus size={14} />
      NEUTRAL
    </span>
  );
}

function SignalDot({ signal }: { signal: WeightedSignal["signal"] }) {
  const color = signal === "bullish" ? "#10B981" : signal === "bearish" ? "#EF4444" : "#94A3B8";
  return (
    <span className="inline-block w-2 h-2 rounded-full" style={{ background: color }} />
  );
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 rounded-full overflow-hidden" style={{ background: "var(--color-border)" }}>
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, background: "var(--color-secondary)" }}
        />
      </div>
      <span className="text-xs font-mono w-10 text-right" style={{ color: "var(--color-muted)" }}>
        {pct}%
      </span>
    </div>
  );
}

export default function PredictionResult({ result }: Props) {
  const { direction, confidence, reasoning, weighted_signals, ticker, run_date } = result;

  return (
    <div className="space-y-4">
      {/* Header row */}
      <div
        className="rounded-lg p-5 border flex flex-wrap items-start justify-between gap-4"
        style={{ background: "var(--color-surface)", borderColor: "var(--color-border)" }}
      >
        <div>
          <p className="text-xs font-mono uppercase tracking-widest mb-1" style={{ color: "var(--color-muted)" }}>
            Prediction — {ticker} &nbsp;·&nbsp; {new Date(run_date).toLocaleString()}
          </p>
          <div className="flex items-center gap-3 mt-2">
            <DirectionBadge direction={direction} />
            <span className="text-2xl font-mono font-bold">{Math.round(confidence * 100)}%</span>
            <span className="text-sm" style={{ color: "var(--color-muted)" }}>confidence</span>
          </div>
        </div>
        <span className="text-xs font-mono" style={{ color: "var(--color-muted)" }}>
          ID: {result.prediction_id.slice(0, 8)}…
        </span>
      </div>

      {/* Reasoning */}
      <div
        className="rounded-lg p-5 border"
        style={{ background: "var(--color-surface)", borderColor: "var(--color-border)" }}
      >
        <h3 className="text-xs font-mono uppercase tracking-widest mb-3" style={{ color: "var(--color-muted)" }}>
          Reasoning
        </h3>
        <p className="text-sm leading-relaxed" style={{ color: "var(--color-text)" }}>
          {reasoning}
        </p>
      </div>

      {/* Agent signals */}
      {weighted_signals && Object.keys(weighted_signals).length > 0 && (
        <div
          className="rounded-lg p-5 border"
          style={{ background: "var(--color-surface)", borderColor: "var(--color-border)" }}
        >
          <h3 className="text-xs font-mono uppercase tracking-widest mb-4" style={{ color: "var(--color-muted)" }}>
            Weighted Agent Signals
          </h3>
          <div className="space-y-3">
            {Object.entries(weighted_signals).map(([agent, data]) => (
              <div key={agent} className="grid grid-cols-[140px_80px_1fr] items-center gap-3">
                <div className="flex items-center gap-2 text-sm">
                  <SignalDot signal={data.signal} />
                  <span className="font-mono text-xs">{AGENT_LABELS[agent] ?? agent}</span>
                </div>
                <span
                  className="text-xs font-mono uppercase"
                  style={{
                    color:
                      data.signal === "bullish"
                        ? "#10B981"
                        : data.signal === "bearish"
                        ? "#EF4444"
                        : "#94A3B8",
                  }}
                >
                  {data.signal}
                </span>
                <ConfidenceBar value={data.weight} />
              </div>
            ))}
          </div>
        </div>
      )}

      {Object.keys(weighted_signals ?? {}).length === 0 && (
        <div className="flex items-center gap-2 text-sm rounded-lg p-4 border" style={{ background: "var(--color-surface)", borderColor: "var(--color-border)", color: "var(--color-muted)" }}>
          <AlertCircle size={14} />
          No agent signal breakdown available.
        </div>
      )}
    </div>
  );
}
