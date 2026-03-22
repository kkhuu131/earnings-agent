import type {
  AgentReputationRecord,
  AnalyzeRequest,
  AnalyzeResponse,
  BacktestProgressEvent,
  BacktestRequest,
  BacktestResponse,
  IngestRequest,
  IngestResponse,
  PredictionRecord,
  TranscriptRecord,
  UpdateDateRequest,
  UpdateDateResponse,
} from "./types";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json() as Promise<T>;
}

export function analyze(payload: AnalyzeRequest): Promise<AnalyzeResponse> {
  return request<AnalyzeResponse>("/analyze", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getPredictions(ticker?: string, limit = 50): Promise<PredictionRecord[]> {
  const params = new URLSearchParams();
  if (ticker) params.set("ticker", ticker);
  params.set("limit", String(limit));
  return request<PredictionRecord[]>(`/predictions?${params.toString()}`);
}

export function ingest(payload: IngestRequest): Promise<IngestResponse> {
  return request<IngestResponse>("/ingest", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function runBacktest(payload: BacktestRequest): Promise<BacktestResponse> {
  return request<BacktestResponse>("/backtest", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function streamBacktest(
  payload: BacktestRequest,
  onEvent: (event: BacktestProgressEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${BASE_URL}/backtest/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      const line = part.trim();
      if (line.startsWith("data: ")) {
        try {
          const event = JSON.parse(line.slice(6)) as BacktestProgressEvent;
          onEvent(event);
        } catch {
          // malformed event — skip
        }
      }
    }
  }
}

export function getReputation(): Promise<AgentReputationRecord[]> {
  return request<AgentReputationRecord[]>("/reputation");
}

export function getTranscripts(): Promise<TranscriptRecord[]> {
  return request<TranscriptRecord[]>("/transcripts");
}

export function updateTranscriptDate(
  id: string,
  payload: UpdateDateRequest,
): Promise<UpdateDateResponse> {
  return request<UpdateDateResponse>(`/transcripts/${id}/date`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}
