"use client";

import { useState } from "react";
import { Search, Loader2, AlertCircle, ChevronDown, ChevronUp } from "lucide-react";
import { analyze } from "@/lib/api";
import type { AnalyzeResponse } from "@/lib/types";
import PredictionResult from "@/components/PredictionResult";
import AgentDebate from "@/components/AgentDebate";

const SAMPLE_PRICE_DATA = {
  ticker: "",
  price_5d_return: 0.02,
  price_30d_return: 0.05,
  rsi_14: 58.3,
  volume_trend: "increasing",
  implied_move: 0.04,
  avg_historical_move: 0.038,
};

export default function AnalyzePage() {
  const [ticker, setTicker] = useState("");
  const [transcript, setTranscript] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AnalyzeResponse | null>(null);
  const [showDebate, setShowDebate] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!ticker.trim() || !transcript.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await analyze({
        ticker: ticker.toUpperCase().trim(),
        transcript: transcript.trim(),
        price_data: { ...SAMPLE_PRICE_DATA, ticker: ticker.toUpperCase().trim() },
      });
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "An unexpected error occurred.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-mono font-bold mb-1" style={{ color: "var(--color-text)" }}>
          Earnings Analysis
        </h1>
        <p className="text-sm" style={{ color: "var(--color-muted)" }}>
          Paste an earnings call transcript to get a multi-agent prediction with reputation-weighted signals.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        {/* Ticker input */}
        <div>
          <label
            htmlFor="ticker"
            className="block text-xs font-mono uppercase tracking-widest mb-1.5"
            style={{ color: "var(--color-muted)" }}
          >
            Ticker Symbol
          </label>
          <input
            id="ticker"
            type="text"
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            placeholder="e.g. AAPL"
            maxLength={10}
            className="w-full rounded-lg px-4 py-2.5 text-sm font-mono border outline-none transition-colors duration-200 focus:border-blue-500"
            style={{
              background: "var(--color-surface)",
              borderColor: "var(--color-border)",
              color: "var(--color-text)",
            }}
            required
          />
        </div>

        {/* Transcript textarea */}
        <div>
          <label
            htmlFor="transcript"
            className="block text-xs font-mono uppercase tracking-widest mb-1.5"
            style={{ color: "var(--color-muted)" }}
          >
            Earnings Call Transcript
          </label>
          <textarea
            id="transcript"
            value={transcript}
            onChange={(e) => setTranscript(e.target.value)}
            placeholder="Paste the full earnings call transcript here…"
            rows={12}
            className="w-full rounded-lg px-4 py-3 text-sm border outline-none transition-colors duration-200 focus:border-blue-500 resize-y"
            style={{
              background: "var(--color-surface)",
              borderColor: "var(--color-border)",
              color: "var(--color-text)",
              lineHeight: "1.6",
            }}
            required
          />
        </div>

        <button
          type="submit"
          disabled={loading || !ticker.trim() || !transcript.trim()}
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold font-mono cursor-pointer transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed hover:brightness-110"
          style={{ background: "var(--color-primary)", color: "#fff" }}
        >
          {loading ? (
            <>
              <Loader2 size={15} className="animate-spin" />
              Running pipeline…
            </>
          ) : (
            <>
              <Search size={15} />
              Analyze
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
          <span>{error}</span>
        </div>
      )}

      {/* Result */}
      {result && (
        <div className="space-y-4">
          <PredictionResult result={result} />

          {/* Debate toggle — the AnalyzeResponse doesn't carry debate_transcript
              but we keep this section for when it does in future */}
          <button
            type="button"
            onClick={() => setShowDebate((v) => !v)}
            className="inline-flex items-center gap-1.5 text-xs font-mono cursor-pointer transition-colors duration-200 hover:text-white"
            style={{ color: "var(--color-muted)" }}
          >
            {showDebate ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
            {showDebate ? "Hide" : "Show"} debate transcript
          </button>

          {showDebate && <AgentDebate rounds={[]} />}
        </div>
      )}
    </div>
  );
}
