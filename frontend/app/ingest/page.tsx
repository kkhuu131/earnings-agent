"use client";

import { useState } from "react";
import { Upload, Loader2, AlertCircle, CheckCircle2, XCircle } from "lucide-react";
import { ingest } from "@/lib/api";
import type { IngestResponse } from "@/lib/types";

const CURRENT_YEAR = new Date().getFullYear();
const START_YEAR = 2022;

// Generate all quarters from START_YEAR Q1 → current quarter, newest first
const QUARTER_OPTIONS: string[] = [];
for (let y = CURRENT_YEAR; y >= START_YEAR; y--) {
  const maxQ = y === CURRENT_YEAR ? Math.ceil(new Date().getMonth() / 3) + 1 : 4;
  for (let q = Math.min(maxQ, 4); q >= 1; q--) {
    QUARTER_OPTIONS.push(`Q${q} ${y}`);
  }
}

export default function IngestPage() {
  const [ticker, setTicker] = useState("");
  const [fiscalQuarter, setFiscalQuarter] = useState("");
  const [filingDate, setFilingDate] = useState("");
  const [transcriptText, setTranscriptText] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<IngestResponse | null>(null);

  const wordCount = transcriptText.trim() ? transcriptText.trim().split(/\s+/).length : 0;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!ticker.trim() || !fiscalQuarter || !filingDate || !transcriptText.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await ingest({
        ticker: ticker.toUpperCase().trim(),
        fiscal_quarter: fiscalQuarter,
        filing_date: filingDate,
        transcript_text: transcriptText.trim(),
      });
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "An unexpected error occurred.");
    } finally {
      setLoading(false);
    }
  }

  function handleReset() {
    setTicker("");
    setFiscalQuarter("");
    setFilingDate("");
    setTranscriptText("");
    setResult(null);
    setError(null);
  }

  return (
    <div className="max-w-3xl space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-mono font-bold mb-1" style={{ color: "var(--color-text)" }}>
          Ingest Transcript
        </h1>
        <p className="text-sm" style={{ color: "var(--color-muted)" }}>
          Paste an earnings call transcript to store it in the backtest database. Copy transcripts
          from{" "}
          <a
            href="https://www.fool.com/earnings-call-transcripts/"
            target="_blank"
            rel="noopener noreferrer"
            className="underline hover:text-white transition-colors"
          >
            Motley Fool
          </a>{" "}
          or any public source. Once ingested, the transcript can be used in backtests to evaluate
          and update agent reputation weights.
        </p>
      </div>

      {/* Form */}
      {!result && (
        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Row: ticker + quarter + date */}
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label
                htmlFor="ticker"
                className="block text-xs font-mono uppercase tracking-widest mb-1.5"
                style={{ color: "var(--color-muted)" }}
              >
                Ticker
              </label>
              <input
                id="ticker"
                type="text"
                value={ticker}
                onChange={(e) => setTicker(e.target.value)}
                placeholder="AAPL"
                maxLength={10}
                required
                className="w-full rounded-lg px-3 py-2.5 text-sm font-mono border outline-none transition-colors focus:border-blue-500"
                style={{
                  background: "var(--color-surface)",
                  borderColor: "var(--color-border)",
                  color: "var(--color-text)",
                }}
              />
            </div>

            <div>
              <label
                htmlFor="quarter"
                className="block text-xs font-mono uppercase tracking-widest mb-1.5"
                style={{ color: "var(--color-muted)" }}
              >
                Fiscal Quarter
              </label>
              <select
                id="quarter"
                value={fiscalQuarter}
                onChange={(e) => setFiscalQuarter(e.target.value)}
                required
                className="w-full rounded-lg px-3 py-2.5 text-sm font-mono border outline-none transition-colors focus:border-blue-500"
                style={{
                  background: "var(--color-surface)",
                  borderColor: "var(--color-border)",
                  color: fiscalQuarter ? "var(--color-text)" : "var(--color-muted)",
                }}
              >
                <option value="" disabled>Select…</option>
                {QUARTER_OPTIONS.map((q) => (
                  <option key={q} value={q}>{q}</option>
                ))}
              </select>
            </div>

            <div>
              <label
                htmlFor="date"
                className="block text-xs font-mono uppercase tracking-widest mb-1.5"
                style={{ color: "var(--color-muted)" }}
              >
                Earnings Date
              </label>
              <input
                id="date"
                type="date"
                value={filingDate}
                onChange={(e) => setFilingDate(e.target.value)}
                required
                className="w-full rounded-lg px-3 py-2.5 text-sm font-mono border outline-none transition-colors focus:border-blue-500"
                style={{
                  background: "var(--color-surface)",
                  borderColor: "var(--color-border)",
                  color: "var(--color-text)",
                }}
              />
            </div>
          </div>

          {/* Transcript textarea */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label
                htmlFor="transcript"
                className="block text-xs font-mono uppercase tracking-widest"
                style={{ color: "var(--color-muted)" }}
              >
                Transcript Text
              </label>
              {wordCount > 0 && (
                <span className="text-xs font-mono" style={{ color: wordCount < 1000 ? "#F59E0B" : "var(--color-muted)" }}>
                  {wordCount.toLocaleString()} words{wordCount < 1000 ? " — paste the full transcript" : ""}
                </span>
              )}
            </div>
            <textarea
              id="transcript"
              value={transcriptText}
              onChange={(e) => setTranscriptText(e.target.value)}
              placeholder="Paste the full earnings call transcript here…"
              rows={14}
              required
              className="w-full rounded-lg px-4 py-3 text-sm border outline-none transition-colors focus:border-blue-500 resize-y"
              style={{
                background: "var(--color-surface)",
                borderColor: "var(--color-border)",
                color: "var(--color-text)",
                lineHeight: "1.6",
              }}
            />
          </div>

          <button
            type="submit"
            disabled={loading || !ticker.trim() || !fiscalQuarter || !filingDate || wordCount < 100}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold font-mono cursor-pointer transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed hover:brightness-110"
            style={{ background: "var(--color-primary)", color: "#fff" }}
          >
            {loading ? (
              <>
                <Loader2 size={15} className="animate-spin" />
                Saving…
              </>
            ) : (
              <>
                <Upload size={15} />
                Ingest Transcript
              </>
            )}
          </button>
        </form>
      )}

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

      {/* Success result */}
      {result && (
        <div className="space-y-4">
          <div
            className="rounded-lg border p-5 space-y-4"
            style={{ background: "var(--color-surface)", borderColor: "var(--color-border)" }}
          >
            <div className="flex items-center gap-2">
              <CheckCircle2 size={18} style={{ color: "#10B981" }} />
              <span className="font-mono font-semibold text-sm" style={{ color: "#10B981" }}>
                Transcript ingested
              </span>
            </div>

            <div className="grid grid-cols-2 gap-3 text-sm">
              <Stat label="Ticker" value={result.ticker} />
              <Stat label="Quarter" value={result.fiscal_quarter} />
              <Stat label="Earnings date" value={result.filing_date} />
              <Stat label="Word count" value={result.word_count.toLocaleString()} />
              <div className="col-span-2">
                <span className="text-xs font-mono uppercase tracking-widest block mb-1" style={{ color: "var(--color-muted)" }}>
                  Price snapshot
                </span>
                {result.price_snapshot_found ? (
                  <div className="flex items-center gap-2">
                    <CheckCircle2 size={14} style={{ color: "#10B981" }} />
                    <span style={{ color: "var(--color-text)" }}>
                      Found —{" "}
                      {result.actual_direction
                        ? `30-day direction: ${result.actual_direction.toUpperCase()}`
                        : "30-day outcome not yet available (earnings too recent)"}
                    </span>
                  </div>
                ) : (
                  <div className="flex items-center gap-2">
                    <XCircle size={14} style={{ color: "#F59E0B" }} />
                    <span style={{ color: "var(--color-muted)" }}>
                      No price data found for this date — backtest accuracy won't be computed for this record
                    </span>
                  </div>
                )}
              </div>
            </div>

            <p className="text-xs" style={{ color: "var(--color-muted)" }}>
              ID: {result.transcript_id}
            </p>
          </div>

          <button
            type="button"
            onClick={handleReset}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold font-mono cursor-pointer transition-all duration-200 hover:brightness-110"
            style={{ background: "var(--color-surface)", color: "var(--color-text)", border: "1px solid var(--color-border)" }}
          >
            <Upload size={15} />
            Ingest another
          </button>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <span className="text-xs font-mono uppercase tracking-widest block mb-0.5" style={{ color: "var(--color-muted)" }}>
        {label}
      </span>
      <span className="text-sm font-mono" style={{ color: "var(--color-text)" }}>{value}</span>
    </div>
  );
}
