"use client";

import { useEffect, useState } from "react";
import { TrendingUp, TrendingDown, Minus, Loader2, AlertCircle, CheckCircle2, XCircle } from "lucide-react";
import { getPredictions } from "@/lib/api";
import type { PredictionRecord } from "@/lib/types";
import AgentDebate from "@/components/AgentDebate";

function DirectionIcon({ direction }: { direction: string | null }) {
  if (direction === "up") return <TrendingUp size={14} style={{ color: "#10B981" }} />;
  if (direction === "down") return <TrendingDown size={14} style={{ color: "#EF4444" }} />;
  return <Minus size={14} style={{ color: "#94A3B8" }} />;
}

function DirectionLabel({ direction }: { direction: string | null }) {
  const color = direction === "up" ? "#10B981" : direction === "down" ? "#EF4444" : "#94A3B8";
  return (
    <span className="font-mono text-xs uppercase" style={{ color }}>
      {direction ?? "—"}
    </span>
  );
}

function CorrectnessIcon({ wasCorrect }: { wasCorrect: boolean | null }) {
  if (wasCorrect === true) return <CheckCircle2 size={14} style={{ color: "#10B981" }} />;
  if (wasCorrect === false) return <XCircle size={14} style={{ color: "#EF4444" }} />;
  return <span className="text-xs font-mono" style={{ color: "#94A3B8" }}>—</span>;
}

function ExpandedRow({ record }: { record: PredictionRecord }) {
  return (
    <tr>
      <td
        colSpan={7}
        className="px-6 py-4"
        style={{ borderBottom: `1px solid var(--color-border)` }}
      >
        <div className="space-y-4 max-w-3xl">
          {record.final_reasoning && (
            <div>
              <p className="text-xs font-mono uppercase tracking-widest mb-1" style={{ color: "var(--color-muted)" }}>
                Reasoning
              </p>
              <p className="text-sm leading-relaxed" style={{ color: "var(--color-text)" }}>
                {record.final_reasoning}
              </p>
            </div>
          )}
          {record.debate_transcript && record.debate_transcript.length > 0 && (
            <AgentDebate rounds={record.debate_transcript} />
          )}
        </div>
      </td>
    </tr>
  );
}

export default function HistoryPage() {
  const [records, setRecords] = useState<PredictionRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tickerFilter, setTickerFilter] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  useEffect(() => {
    setLoading(true);
    setError(null);
    getPredictions(tickerFilter.trim() || undefined, 100)
      .then(setRecords)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load predictions."))
      .finally(() => setLoading(false));
  }, [tickerFilter]);

  function toggleExpand(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-mono font-bold mb-1" style={{ color: "var(--color-text)" }}>
          Prediction History
        </h1>
        <p className="text-sm" style={{ color: "var(--color-muted)" }}>
          All past analysis runs. Click a row to expand reasoning and debate.
        </p>
      </div>

      {/* Filter */}
      <div className="flex items-center gap-3">
        <input
          type="text"
          value={tickerFilter}
          onChange={(e) => setTickerFilter(e.target.value.toUpperCase())}
          placeholder="Filter by ticker…"
          className="rounded-lg px-4 py-2 text-sm font-mono border outline-none transition-colors duration-200 focus:border-blue-500 w-48"
          style={{
            background: "var(--color-surface)",
            borderColor: "var(--color-border)",
            color: "var(--color-text)",
          }}
        />
        {tickerFilter && (
          <button
            type="button"
            onClick={() => setTickerFilter("")}
            className="text-xs font-mono cursor-pointer transition-colors duration-200 hover:text-white"
            style={{ color: "var(--color-muted)" }}
          >
            Clear
          </button>
        )}
      </div>

      {/* Error */}
      {error && (
        <div
          className="flex items-start gap-3 rounded-lg p-4 border text-sm"
          style={{ background: "#450A0A", borderColor: "#7F1D1D", color: "#FCA5A5" }}
          role="alert"
        >
          <AlertCircle size={16} className="mt-0.5 shrink-0" />
          {error}
        </div>
      )}

      {/* Table */}
      <div
        className="rounded-lg border overflow-hidden"
        style={{ background: "var(--color-surface)", borderColor: "var(--color-border)" }}
      >
        {loading ? (
          <div className="flex items-center justify-center gap-2 py-16 text-sm" style={{ color: "var(--color-muted)" }}>
            <Loader2 size={16} className="animate-spin" />
            Loading…
          </div>
        ) : records.length === 0 ? (
          <div className="py-16 text-center text-sm" style={{ color: "var(--color-muted)" }}>
            No predictions found.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr style={{ borderBottom: `1px solid var(--color-border)` }}>
                {["Ticker", "Date", "Direction", "Confidence", "Actual", "Correct", ""].map((h) => (
                  <th
                    key={h}
                    className="text-left px-4 py-3 font-mono text-xs uppercase tracking-widest"
                    style={{ color: "var(--color-muted)" }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {records.map((r, i) => {
                const isExpanded = expanded.has(r.id);
                const hasDetails = !!(r.final_reasoning || (r.debate_transcript && r.debate_transcript.length > 0));
                return [
                  <tr
                    key={r.id}
                    onClick={hasDetails ? () => toggleExpand(r.id) : undefined}
                    className={`transition-colors duration-150 hover:bg-white/5 ${hasDetails ? "cursor-pointer" : ""}`}
                    style={{ borderBottom: !isExpanded && i < records.length - 1 ? `1px solid var(--color-border)` : "none" }}
                  >
                    <td className="px-4 py-3 font-mono font-semibold" style={{ color: "var(--color-secondary)" }}>
                      {r.ticker}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs" style={{ color: "var(--color-muted)" }}>
                      {new Date(r.run_date).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1.5">
                        <DirectionIcon direction={r.final_direction} />
                        <DirectionLabel direction={r.final_direction} />
                      </div>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs" style={{ color: "var(--color-text)" }}>
                      {r.final_confidence != null ? `${Math.round(r.final_confidence * 100)}%` : "—"}
                    </td>
                    <td className="px-4 py-3">
                      <DirectionLabel direction={r.actual_direction} />
                    </td>
                    <td className="px-4 py-3">
                      <CorrectnessIcon wasCorrect={r.was_correct} />
                    </td>
                    <td className="px-4 py-3 text-xs font-mono" style={{ color: "var(--color-muted)" }}>
                      {hasDetails && (isExpanded ? "▲" : "▼")}
                    </td>
                  </tr>,
                  isExpanded && <ExpandedRow key={`${r.id}-expanded`} record={r} />,
                ];
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
