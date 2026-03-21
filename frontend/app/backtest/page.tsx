"use client";

import { useState } from "react";
import { Play, Loader2, AlertCircle, X } from "lucide-react";
import { runBacktest } from "@/lib/api";
import type { BacktestResponse } from "@/lib/types";
import ReputationChart from "@/components/ReputationChart";

export default function BacktestPage() {
  const [tickers, setTickers] = useState<string[]>([]);
  const [tickerInput, setTickerInput] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BacktestResponse | null>(null);

  function addTicker() {
    const t = tickerInput.toUpperCase().trim();
    if (t && !tickers.includes(t)) {
      setTickers((prev) => [...prev, t]);
    }
    setTickerInput("");
  }

  function removeTicker(t: string) {
    setTickers((prev) => prev.filter((x) => x !== t));
  }

  function handleTickerKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") {
      e.preventDefault();
      addTicker();
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (tickers.length === 0 || !startDate || !endDate) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await runBacktest({
        tickers,
        start_date: startDate,
        end_date: endDate,
      });
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Backtest failed.");
    } finally {
      setLoading(false);
    }
  }

  const isValid = tickers.length > 0 && !!startDate && !!endDate && startDate < endDate;

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
          <label
            className="block text-xs font-mono uppercase tracking-widest mb-1.5"
            style={{ color: "var(--color-muted)" }}
          >
            Tickers
          </label>
          <div className="flex gap-2 mb-2 flex-wrap">
            {tickers.map((t) => (
              <span
                key={t}
                className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-mono"
                style={{ background: "var(--color-primary)", color: "#fff" }}
              >
                {t}
                <button
                  type="button"
                  onClick={() => removeTicker(t)}
                  className="cursor-pointer hover:opacity-70 transition-opacity"
                  aria-label={`Remove ${t}`}
                >
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
              style={{
                background: "var(--color-surface)",
                borderColor: "var(--color-border)",
                color: "var(--color-text)",
              }}
            />
            <button
              type="button"
              onClick={addTicker}
              className="px-4 py-2.5 rounded-lg text-sm font-mono cursor-pointer transition-colors duration-200 border hover:bg-white/5"
              style={{
                background: "transparent",
                borderColor: "var(--color-border)",
                color: "var(--color-text)",
              }}
            >
              Add
            </button>
          </div>
        </div>

        {/* Date range */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label
              htmlFor="start-date"
              className="block text-xs font-mono uppercase tracking-widest mb-1.5"
              style={{ color: "var(--color-muted)" }}
            >
              Start Date
            </label>
            <input
              id="start-date"
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="w-full rounded-lg px-4 py-2.5 text-sm font-mono border outline-none transition-colors duration-200 focus:border-blue-500"
              style={{
                background: "var(--color-surface)",
                borderColor: "var(--color-border)",
                color: "var(--color-text)",
                colorScheme: "dark",
              }}
              required
            />
          </div>
          <div>
            <label
              htmlFor="end-date"
              className="block text-xs font-mono uppercase tracking-widest mb-1.5"
              style={{ color: "var(--color-muted)" }}
            >
              End Date
            </label>
            <input
              id="end-date"
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="w-full rounded-lg px-4 py-2.5 text-sm font-mono border outline-none transition-colors duration-200 focus:border-blue-500"
              style={{
                background: "var(--color-surface)",
                borderColor: "var(--color-border)",
                color: "var(--color-text)",
                colorScheme: "dark",
              }}
              required
            />
          </div>
        </div>

        {startDate && endDate && startDate >= endDate && (
          <p className="text-xs font-mono" style={{ color: "#EF4444" }}>
            End date must be after start date.
          </p>
        )}

        <button
          type="submit"
          disabled={loading || !isValid}
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold font-mono cursor-pointer transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed hover:brightness-110"
          style={{ background: "var(--color-cta)", color: "#000" }}
        >
          {loading ? (
            <>
              <Loader2 size={15} className="animate-spin" />
              Running backtest…
            </>
          ) : (
            <>
              <Play size={15} />
              Run Backtest
            </>
          )}
        </button>
      </form>

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

      {/* Results */}
      {result && (
        <div className="space-y-2">
          <h2 className="text-sm font-mono uppercase tracking-widest" style={{ color: "var(--color-muted)" }}>
            Results
          </h2>
          <ReputationChart result={result} />
        </div>
      )}
    </div>
  );
}
