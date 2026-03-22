// ---------------------------------------------------------------------------
// POST /analyze
// ---------------------------------------------------------------------------

export interface AnalyzeRequest {
  ticker: string;
  transcript: string;
  price_data: Record<string, unknown>;
}

export interface AnalyzeResponse {
  prediction_id: string;
  ticker: string;
  run_date: string;
  direction: "up" | "down" | "neutral";
  confidence: number;
  reasoning: string;
  weighted_signals: Record<string, WeightedSignal>;
  debate_transcript: DebateRound[] | null;
}

export interface WeightedSignal {
  signal: "bullish" | "bearish" | "neutral";
  weight: number;
}

// ---------------------------------------------------------------------------
// GET /predictions
// ---------------------------------------------------------------------------

export interface AgentReport {
  signal: "bullish" | "bearish" | "neutral";
  key_points: string[];
  confidence: number;
}

export interface DebateRound {
  bull: {
    argument: string;
    confidence: number;
    rebuttals: string[];
  };
  bear: {
    argument: string;
    confidence: number;
    rebuttals: string[];
  };
}

export interface PredictionRecord {
  id: string;
  ticker: string;
  run_date: string;
  final_direction: "up" | "down" | "neutral" | null;
  final_confidence: number | null;
  final_reasoning: string | null;
  agent_reports: Record<string, AgentReport> | null;
  debate_transcript: DebateRound[] | null;
  weighted_signals: Record<string, WeightedSignal> | null;
  actual_direction: "up" | "down" | "neutral" | null;
  was_correct: boolean | null;
}

// ---------------------------------------------------------------------------
// POST /ingest
// ---------------------------------------------------------------------------

export interface IngestRequest {
  ticker: string;
  fiscal_quarter: string;   // e.g. "Q1 2025"
  filing_date: string;      // ISO date: "2025-01-30"
  transcript_text: string;
}

export interface IngestResponse {
  transcript_id: string;
  ticker: string;
  fiscal_quarter: string;
  filing_date: string;
  word_count: number;
  price_snapshot_found: boolean;
  actual_direction: "up" | "down" | "neutral" | null;
}

// ---------------------------------------------------------------------------
// GET /transcripts  +  PATCH /transcripts/{id}/date
// ---------------------------------------------------------------------------

export interface TranscriptRecord {
  id: string;
  ticker: string;
  fiscal_quarter: string | null;
  filing_date: string | null;
  word_count: number | null;
  price_snapshot_found: boolean;
  actual_direction: "up" | "down" | "neutral" | null;
}

export interface UpdateDateRequest {
  filing_date: string; // ISO date: "2025-01-30"
}

export interface UpdateDateResponse {
  transcript_id: string;
  filing_date: string;
  price_snapshot_found: boolean;
  actual_direction: "up" | "down" | "neutral" | null;
}

// ---------------------------------------------------------------------------
// POST /backtest
// ---------------------------------------------------------------------------

export interface BacktestRequest {
  tickers: string[];
  start_date: string;
  end_date: string;
}

export interface TickerSummary {
  total: number;
  correct: number;
  accuracy: number;
}

export interface BacktestResponse {
  total: number;
  correct: number;
  accuracy: number;
  per_ticker: Record<string, TickerSummary>;
}

// ---------------------------------------------------------------------------
// GET /reputation
// ---------------------------------------------------------------------------

export interface AgentReputationRecord {
  agent_name: string;
  correct_predictions: number;
  total_predictions: number;
  accuracy: number;
  weight: number;
}

// ---------------------------------------------------------------------------
// POST /backtest/stream  (Server-Sent Events)
// ---------------------------------------------------------------------------

export type BacktestProgressEvent =
  | { type: "start"; total: number }
  | { type: "running"; index: number; total: number; ticker: string; date: string }
  | {
      type: "result";
      index: number;
      total: number;
      ticker: string;
      date: string;
      direction: string | null;
      actual_direction: string | null;
      was_correct: boolean | null;
    }
  | { type: "skip"; index: number; total: number; ticker: string; date: string; reason: string }
  | { type: "error"; index: number; total: number; ticker: string; date: string; message: string }
  | { type: "done"; total: number; correct: number; accuracy: number; per_ticker: Record<string, TickerSummary> }
  | { type: "stream_error"; message: string };
