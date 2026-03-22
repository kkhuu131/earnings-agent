"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Play, Square, AlertCircle, X, CheckCircle2, XCircle, SkipForward, Loader2 } from "lucide-react";
import { getReputation, streamBacktest } from "@/lib/api";
import type { AgentReputationRecord, BacktestProgressEvent, BacktestResponse } from "@/lib/types";
import ReputationChart from "@/components/ReputationChart";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type LogEntry =
  | { kind: "running"; ticker: string; date: string; index: number; total: number }
  | { kind: "result"; ticker: string; date: string; index: number; total: number; direction: string | null; actual: string | null; correct: boolean | null }
  | { kind: "skip"; ticker: string; date: string; index: number; total: number; reason: string }
  | { kind: "error"; ticker: string; date: string; index: number; total: number; message: string };

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function directionLabel(d: string | null) {
  if (d === "up") return <span className="font-mono text-xs px-1.5 py-0.5 rounded" style={{ background: "#14532d", color: "#86efac" }}>UP</span>;
  if (d === "down") return <span className="font-mono text-xs px-1.5 py-0.5 rounded" style={{ background: "#450a0a", color: "#fca5a5" }}>DOWN</span>;
  return <span className="font-mono text-xs px-1.5 py-0.5 rounded" style={{ background: "#1c1917", color: "#a8a29e" }}>NEUTRAL</span>;
}

function skipReason(reason: string) {
  if (reason === "no_price_snapshot") return "no price data";
  if (reason === "no_transcript_text") return "empty transcript";
  return reason;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function BacktestPage() {
  const [tickers, setTickers] = useState<string[]>([]);
  const [tickerInput, setTickerInput] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");

  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BacktestResponse | null>(null);
  const [reputation, setReputation] = useState<AgentReputationRecord[]>([]);

  const fetchReputation = useCallback(async () => {
    try {
      setReputation(await getReputation());
    } catch {
      // silently ignore — no data yet is fine
    }
  }, []);

  useEffect(() => { fetchReputation(); }, [fetchReputation]);

  // Progress state
  const [progressTotal, setProgressTotal] = useState(0);
  const [progressCurrent, setProgressCurrent] = useState(0);
  const [currentStatus, setCurrentStatus] = useState<string | null>(null);
  const [log, setLog] = useState<LogEntry[]>([]);

  const abortRef = useRef<AbortController | null>(null);
  const logEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll log to bottom
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [log]);

  function addTicker() {
    const t = tickerInput.toUpperCase().trim();
    if (t && !tickers.includes(t)) setTickers((prev) => [...prev, t]);
    setTickerInput("");
  }

  function removeTicker(t: string) {
    setTickers((prev) => prev.filter((x) => x !== t));
  }

  function handleTickerKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") { e.preventDefault(); addTicker(); }
  }

  function handleStop() {
    abortRef.current?.abort();
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (tickers.length === 0 || !startDate || !endDate) return;

    const controller = new AbortController();
    abortRef.current = controller;

    setRunning(true);
    setError(null);
    setResult(null);
    setLog([]);
    setProgressTotal(0);
    setProgressCurrent(0);
    setCurrentStatus(null);

    try {
      await streamBacktest(
        { tickers, start_date: startDate, end_date: endDate },
        (event: BacktestProgressEvent) => {
          switch (event.type) {
            case "start":
              setProgressTotal(event.total);
              setCurrentStatus(`Found ${event.total} transcript${event.total !== 1 ? "s" : ""} — starting…`);
              break;

            case "running":
              setProgressCurrent(event.index);
              setCurrentStatus(`Running pipeline — ${event.ticker} · ${event.date}`);
              setLog((prev) => {
                // Replace existing "running" entry for this index if any, or append
                const filtered = prev.filter((e) => !(e.kind === "running" && e.index === event.index));
                return [...filtered, { kind: "running", ticker: event.ticker, date: event.date, index: event.index, total: event.total }];
              });
              break;

            case "result":
              setProgressCurrent(event.index);
              setCurrentStatus(null);
              setLog((prev) => {
                const filtered = prev.filter((e) => !(e.kind === "running" && e.index === event.index));
                return [...filtered, { kind: "result", ticker: event.ticker, date: event.date, index: event.index, total: event.total, direction: event.direction, actual: event.actual_direction, correct: event.was_correct }];
              });
              break;

            case "skip":
              setProgressCurrent(event.index);
              setLog((prev) => [...prev, { kind: "skip", ticker: event.ticker, date: event.date, index: event.index, total: event.total, reason: event.reason }]);
              break;

            case "error":
              setProgressCurrent(event.index);
              setLog((prev) => [...prev, { kind: "error", ticker: event.ticker, date: event.date, index: event.index, total: event.total, message: event.message }]);
              break;

            case "done":
              setCurrentStatus(null);
              setProgressCurrent(event.total);
              setProgressTotal(event.total);
              setResult({ total: event.total, correct: event.correct, accuracy: event.accuracy, per_ticker: event.per_ticker });
              fetchReputation();
              break;

            case "stream_error":
              setError(event.message);
              break;
          }
        },
        controller.signal,
      );
    } catch (err) {
      if (err instanceof Error && err.name !== "AbortError") {
        setError(err.message);
      }
    } finally {
      setRunning(false);
      setCurrentStatus(null);
    }
  }

  const isValid = tickers.length > 0 && !!startDate && !!endDate && startDate < endDate;
  const pct = progressTotal > 0 ? Math.round((progressCurrent / progressTotal) * 100) : 0;
  const completed = log.filter((e) => e.kind === "result" || e.kind === "skip" || e.kind === "error").length;

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-mono font-bold mb-1" style={{ color: "var(--color-text)" }}>
          Backtest
        </h1>
        <p className="text-sm" style={{ color: "var(--color-muted)" }}>
          Run the full agent pipeline against historical earnings calls and measure 30-day direction accuracy.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-5">
        {/* Tickers */}
        <div>
          <label className="block text-xs font-mono uppercase tracking-widest mb-1.5" style={{ color: "var(--color-muted)" }}>
            Tickers
          </label>
          <div className="flex gap-2 mb-2 flex-wrap">
            {tickers.map((t) => (
              <span key={t} className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-mono" style={{ background: "var(--color-primary)", color: "#fff" }}>
                {t}
                <button type="button" onClick={() => removeTicker(t)} className="cursor-pointer hover:opacity-70 transition-opacity" aria-label={`Remove ${t}`}>
                  <X size={11} />
                </button>
              </span>
            ))}
          </div>
          <div className="flex gap-2">
            <input
              type="text"
              value={tickerInput}
              onChange={(e) => setTickerInput(e.target.value.toUpperCase())}
              onKeyDown={handleTickerKeyDown}
              placeholder="AAPL — press Enter to add"
              maxLength={10}
              className="flex-1 rounded-lg px-4 py-2.5 text-sm font-mono border outline-none transition-colors duration-200 focus:border-blue-500"
              style={{ background: "var(--color-surface)", borderColor: "var(--color-border)", color: "var(--color-text)" }}
            />
            <button
              type="button"
              onClick={addTicker}
              className="px-4 py-2.5 rounded-lg text-sm font-mono cursor-pointer transition-colors duration-200 border hover:bg-white/5"
              style={{ background: "transparent", borderColor: "var(--color-border)", color: "var(--color-text)" }}
            >
              Add
            </button>
          </div>
        </div>

        {/* Date range */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label htmlFor="start-date" className="block text-xs font-mono uppercase tracking-widest mb-1.5" style={{ color: "var(--color-muted)" }}>
              Start Date
            </label>
            <input
              id="start-date"
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="w-full rounded-lg px-4 py-2.5 text-sm font-mono border outline-none transition-colors duration-200 focus:border-blue-500"
              style={{ background: "var(--color-surface)", borderColor: "var(--color-border)", color: "var(--color-text)", colorScheme: "dark" }}
              required
            />
          </div>
          <div>
            <label htmlFor="end-date" className="block text-xs font-mono uppercase tracking-widest mb-1.5" style={{ color: "var(--color-muted)" }}>
              End Date
            </label>
            <input
              id="end-date"
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="w-full rounded-lg px-4 py-2.5 text-sm font-mono border outline-none transition-colors duration-200 focus:border-blue-500"
              style={{ background: "var(--color-surface)", borderColor: "var(--color-border)", color: "var(--color-text)", colorScheme: "dark" }}
              required
            />
          </div>
        </div>

        {startDate && endDate && startDate >= endDate && (
          <p className="text-xs font-mono" style={{ color: "#EF4444" }}>
            End date must be after start date.
          </p>
        )}

        <div className="flex gap-3">
          <button
            type="submit"
            disabled={running || !isValid}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold font-mono cursor-pointer transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed hover:brightness-110"
            style={{ background: "var(--color-cta)", color: "#000" }}
          >
            {running ? <Loader2 size={15} className="animate-spin" /> : <Play size={15} />}
            {running ? "Running…" : "Run Backtest"}
          </button>

          {running && (
            <button
              type="button"
              onClick={handleStop}
              className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-mono cursor-pointer transition-colors duration-200 border hover:bg-white/5"
              style={{ borderColor: "var(--color-border)", color: "var(--color-muted)" }}
            >
              <Square size={13} />
              Stop
            </button>
          )}
        </div>
      </form>

      {/* Error */}
      {error && (
        <div className="flex items-start gap-3 rounded-lg p-4 border text-sm" style={{ background: "#450A0A", borderColor: "#7F1D1D", color: "#FCA5A5" }} role="alert">
          <AlertCircle size={16} className="mt-0.5 shrink-0" />
          {error}
        </div>
      )}

      {/* Live progress panel */}
      {(running || (log.length > 0 && !result)) && (
        <div className="rounded-xl border overflow-hidden" style={{ borderColor: "var(--color-border)", background: "var(--color-surface)" }}>
          {/* Header */}
          <div className="px-4 py-3 border-b flex items-center justify-between" style={{ borderColor: "var(--color-border)" }}>
            <div className="flex items-center gap-2.5">
              {running && <Loader2 size={13} className="animate-spin" style={{ color: "var(--color-primary)" }} />}
              <span className="text-xs font-mono uppercase tracking-widest" style={{ color: "var(--color-muted)" }}>
                {running ? "Running" : "Stopped"}
              </span>
              {progressTotal > 0 && (
                <span className="text-xs font-mono" style={{ color: "var(--color-text)" }}>
                  {completed} / {progressTotal}
                </span>
              )}
            </div>
            {progressTotal > 0 && (
              <span className="text-xs font-mono tabular-nums" style={{ color: "var(--color-primary)" }}>
                {pct}%
              </span>
            )}
          </div>

          {/* Progress bar */}
          {progressTotal > 0 && (
            <div className="h-1 w-full" style={{ background: "var(--color-border)" }}>
              <div
                className="h-full transition-all duration-500 ease-out"
                style={{ width: `${pct}%`, background: "var(--color-primary)" }}
              />
            </div>
          )}

          {/* Current status */}
          {currentStatus && (
            <div className="px-4 py-2.5 border-b text-xs font-mono" style={{ borderColor: "var(--color-border)", color: "var(--color-muted)" }}>
              {currentStatus}
            </div>
          )}

          {/* Log */}
          <div className="divide-y max-h-72 overflow-y-auto" style={{ divideColor: "var(--color-border)" }}>
            {log.map((entry, i) => (
              <div key={i} className="px-4 py-2.5 flex items-center gap-3 text-xs font-mono">
                {/* Icon */}
                {entry.kind === "running" && (
                  <Loader2 size={13} className="animate-spin shrink-0" style={{ color: "var(--color-primary)" }} />
                )}
                {entry.kind === "result" && (
                  entry.correct === true
                    ? <CheckCircle2 size={13} className="shrink-0" style={{ color: "#4ade80" }} />
                    : entry.correct === false
                    ? <XCircle size={13} className="shrink-0" style={{ color: "#f87171" }} />
                    : <CheckCircle2 size={13} className="shrink-0" style={{ color: "var(--color-muted)" }} />
                )}
                {(entry.kind === "skip" || entry.kind === "error") && (
                  <SkipForward size={13} className="shrink-0" style={{ color: "var(--color-muted)" }} />
                )}

                {/* Index badge */}
                <span className="shrink-0 tabular-nums" style={{ color: "var(--color-muted)" }}>
                  {entry.index}/{entry.total}
                </span>

                {/* Ticker */}
                <span className="shrink-0 font-bold" style={{ color: "var(--color-text)" }}>
                  {entry.ticker}
                </span>

                {/* Date */}
                <span className="shrink-0" style={{ color: "var(--color-muted)" }}>
                  {entry.date}
                </span>

                {/* Right side details */}
                <span className="ml-auto flex items-center gap-2 shrink-0">
                  {entry.kind === "running" && (
                    <span style={{ color: "var(--color-muted)" }}>running…</span>
                  )}
                  {entry.kind === "result" && (
                    <>
                      <span style={{ color: "var(--color-muted)" }}>predicted</span>
                      {directionLabel(entry.direction)}
                      <span style={{ color: "var(--color-muted)" }}>actual</span>
                      {directionLabel(entry.actual)}
                    </>
                  )}
                  {entry.kind === "skip" && (
                    <span style={{ color: "var(--color-muted)" }}>skipped — {skipReason(entry.reason)}</span>
                  )}
                  {entry.kind === "error" && (
                    <span style={{ color: "#f87171" }}>{entry.message}</span>
                  )}
                </span>
              </div>
            ))}
            <div ref={logEndRef} />
          </div>
        </div>
      )}

      {/* Results */}
      {result && (
        <div className="space-y-2">
          <h2 className="text-sm font-mono uppercase tracking-widest" style={{ color: "var(--color-muted)" }}>
            Results
          </h2>
          <ReputationChart result={result} />
        </div>
      )}

      {/* Agent reputation weights */}
      <div className="space-y-2">
        <h2 className="text-sm font-mono uppercase tracking-widest" style={{ color: "var(--color-muted)" }}>
          Agent Reputation Weights
        </h2>
        {reputation.length === 0 ? (
          <p className="text-sm font-mono" style={{ color: "var(--color-muted)" }}>
            No data yet — run a backtest to populate agent weights.
          </p>
        ) : (
          <div className="rounded-xl border overflow-hidden" style={{ background: "var(--color-surface)", borderColor: "var(--color-border)" }}>
            <table className="w-full text-sm">
              <thead>
                <tr style={{ borderBottom: `1px solid var(--color-border)` }}>
                  <th className="text-left px-4 py-3 font-mono text-xs uppercase tracking-widest" style={{ color: "var(--color-muted)" }}>Agent</th>
                  <th className="text-right px-4 py-3 font-mono text-xs uppercase tracking-widest" style={{ color: "var(--color-muted)" }}>Correct</th>
                  <th className="text-right px-4 py-3 font-mono text-xs uppercase tracking-widest" style={{ color: "var(--color-muted)" }}>Total</th>
                  <th className="text-right px-4 py-3 font-mono text-xs uppercase tracking-widest" style={{ color: "var(--color-muted)" }}>Accuracy</th>
                  <th className="text-right px-4 py-3 font-mono text-xs uppercase tracking-widest" style={{ color: "var(--color-muted)" }}>Weight</th>
                  <th className="px-4 py-3 w-32" />
                </tr>
              </thead>
              <tbody>
                {reputation.map((row, i) => {
                  const isEqual = Math.abs(row.weight - 1 / reputation.length) < 0.001;
                  return (
                    <tr
                      key={row.agent_name}
                      className="transition-colors duration-150 hover:bg-white/5"
                      style={{ borderBottom: i < reputation.length - 1 ? `1px solid var(--color-border)` : "none" }}
                    >
                      <td className="px-4 py-3 font-mono font-semibold capitalize" style={{ color: "var(--color-text)" }}>
                        {row.agent_name}
                      </td>
                      <td className="px-4 py-3 text-right font-mono tabular-nums" style={{ color: "#10B981" }}>
                        {row.correct_predictions}
                      </td>
                      <td className="px-4 py-3 text-right font-mono tabular-nums" style={{ color: "var(--color-text)" }}>
                        {row.total_predictions}
                      </td>
                      <td className="px-4 py-3 text-right font-mono tabular-nums">
                        <span style={{ color: row.accuracy >= 0.5 ? "#10B981" : "#EF4444" }}>
                          {(row.accuracy * 100).toFixed(1)}%
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right font-mono tabular-nums font-semibold" style={{ color: "var(--color-primary)" }}>
                        {(row.weight * 100).toFixed(1)}%
                      </td>
                      {/* Weight bar */}
                      <td className="px-4 py-3">
                        <div className="relative h-1.5 rounded-full overflow-hidden" style={{ background: "var(--color-border)" }}>
                          <div
                            className="absolute left-0 top-0 h-full rounded-full transition-all duration-500"
                            style={{
                              width: `${row.weight * 100}%`,
                              background: isEqual ? "var(--color-muted)" : "var(--color-primary)",
                            }}
                          />
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
