# earnings-agent

## Project Overview

earnings-agent is a multi-agent LLM framework that analyzes earnings call transcripts to predict post-earnings stock price direction. Specialized AI agents with distinct analytical roles read the same transcript, form independent views, and debate each other before a portfolio manager makes a final prediction.

The novel contribution over existing frameworks like TradingAgents is a **reputation-weighted decision system**: each agent accumulates an accuracy score over historical backtests, and their influence on the final prediction is weighted proportionally to their track record. Agents that are consistently right carry more weight. This is validated against a backtesting framework that runs the full pipeline on historical earnings calls and measures 30-day price direction accuracy.

**This project is built from scratch** — not a fork of TradingAgents. Architecture decisions are original, though the multi-agent debate pattern is inspired by TradingAgents' researcher team structure.

---

## Architecture Overview

```
Data Layer
  └── SEC EDGAR API → fetch earnings call transcripts (10-Q/10-K filings)
  └── yfinance → fetch historical price data for backtesting

Agent Pipeline (LangGraph graph)
  └── Analyst Team (parallel)
        ├── FundamentalsAnalyst  — reads financials, revenue, margins, guidance
        ├── SentimentAnalyst     — reads tone, management confidence, language signals
        └── TechnicalAnalyst     — reads pre-earnings price action and momentum
  └── Researcher Team (sequential debate)
        ├── BullResearcher       — argues for upside, challenges bear
        └── BearResearcher       — argues for downside, challenges bull
  └── PortfolioManager           — reads all reports, makes final prediction

Output
  └── Structured JSON prediction: { direction, confidence, reasoning, agent_reports }
  └── Stored in PostgreSQL for backtesting

Backtesting Framework
  └── Runs pipeline on historical earnings calls
  └── Compares prediction to actual 30-day price movement
  └── Updates agent accuracy scores in DB
  └── Reputation weights recomputed after each backtest run

Frontend (React/Next.js)
  └── Run analysis on a ticker
  └── Watch agent debate in real time (streamed)
  └── Backtest results dashboard with per-agent accuracy over time
  └── Historical prediction log
```

---

## Agent Roles

Each agent receives the transcript and returns a structured JSON report before the debate begins.

### FundamentalsAnalyst
- Reads: revenue growth, EPS vs estimates, gross margin, guidance, capex
- Output: `{ signal: "bullish|bearish|neutral", key_points: [], confidence: 0-1 }`

### SentimentAnalyst  
- Reads: management tone, language hedging, certainty of language, Q&A defensiveness
- Output: `{ signal: "bullish|bearish|neutral", key_points: [], confidence: 0-1 }`

### TechnicalAnalyst
- Reads: pre-earnings price action (5d, 30d), RSI, volume trend, implied move vs historical
- Output: `{ signal: "bullish|bearish|neutral", key_points: [], confidence: 0-1 }`

### BullResearcher
- Receives: all three analyst reports
- Role: synthesize bullish case, challenge bearish assumptions
- Engages in N debate rounds with BearResearcher
- Output: `{ argument: string, confidence: 0-1, rebuttals: [] }`

### BearResearcher
- Receives: all three analyst reports
- Role: synthesize bearish case, challenge bullish assumptions
- Engages in N debate rounds with BullResearcher
- Output: `{ argument: string, confidence: 0-1, rebuttals: [] }`

### PortfolioManager
- Receives: all analyst reports + full debate transcript
- Applies reputation weights to each agent's signal
- Makes final prediction
- Output: `{ direction: "up|down|neutral", confidence: 0-1, reasoning: string, weighted_signals: {} }`

---

## Novel Contribution: Reputation Weighting

Every agent has a `reputation_score` stored in the database. After each backtest:
1. Compare prediction to actual outcome (price up/down 30 days post-earnings)
2. For each agent whose signal matched the final correct prediction, increment their accuracy
3. Recompute weights: `weight = agent_accuracy / sum(all_agent_accuracies)`
4. PortfolioManager uses these weights when synthesizing the final decision

This means over time the system learns which analytical lens is most predictive for different market conditions.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Agent orchestration | LangGraph |
| LLM providers | Configurable: Anthropic Claude, OpenAI GPT, Google Gemini, Ollama (local) |
| Quick tasks (summarization, extraction) | claude-haiku-4-5 or gpt-4o-mini |
| Deep reasoning (debate, final decision) | claude-sonnet-4-6 or gpt-4o |
| Backend API | Python, FastAPI |
| Database | PostgreSQL via Supabase (hosted) |
| Transcript data | SEC EDGAR Full-Text Search API (free, no scraping) |
| Price data | yfinance (free Python library) |
| Frontend | React, Next.js, TypeScript |
| Deployment | Railway or Render (backend), Vercel (frontend) |

---

## LLM Configuration

All LLM calls go through a single `LLMProvider` abstraction. Never hardcode a model — always use config.

```python
# config.py
LLM_CONFIG = {
    "provider": "anthropic",          # anthropic | openai | google | ollama
    "quick_model": "claude-haiku-4-5-20251001",  # for fast, cheap tasks
    "deep_model": "claude-sonnet-4-6",           # for reasoning-heavy tasks
    "temperature": 0.7,
    "max_debate_rounds": 2,
}
```

Switching providers should require only changing this config, not touching agent code.

---

## Database Schema

```sql
-- Earnings call transcripts
CREATE TABLE transcripts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker VARCHAR(10) NOT NULL,
    fiscal_quarter VARCHAR(10),        -- e.g. "Q3 2024"
    filing_date DATE,
    transcript_text TEXT,
    edgar_accession_number VARCHAR(25),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Price data for backtesting
CREATE TABLE price_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker VARCHAR(10) NOT NULL,
    snapshot_date DATE NOT NULL,
    close_price DECIMAL(10,4),
    price_30d_later DECIMAL(10,4),     -- pre-computed for backtest speed
    actual_direction VARCHAR(5)        -- "up" | "down" | "neutral"
);

-- Agent reputation scores
CREATE TABLE agent_reputation (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_name VARCHAR(50) NOT NULL,   -- "fundamentals", "sentiment", "technical", "bull", "bear"
    correct_predictions INT DEFAULT 0,
    total_predictions INT DEFAULT 0,
    accuracy DECIMAL(5,4),             -- recomputed after each backtest
    weight DECIMAL(5,4),               -- normalized weight used in PortfolioManager
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Prediction runs
CREATE TABLE predictions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker VARCHAR(10) NOT NULL,
    transcript_id UUID REFERENCES transcripts(id),
    run_date TIMESTAMPTZ DEFAULT NOW(),
    final_direction VARCHAR(5),        -- "up" | "down" | "neutral"
    final_confidence DECIMAL(5,4),
    final_reasoning TEXT,
    agent_reports JSONB,               -- full report from each agent
    debate_transcript JSONB,           -- full bull/bear debate
    weighted_signals JSONB,            -- how weights were applied
    actual_direction VARCHAR(5),       -- filled in during backtest
    was_correct BOOLEAN                -- filled in during backtest
);
```

---

## Project Structure

```
earnings-agent/
├── CLAUDE.md                          # This file
├── README.md
├── .env.example
├── docker-compose.yml                 # App only (DB is Supabase)
├── pyproject.toml
│
├── backend/
│   ├── main.py                        # FastAPI app entry point
│   ├── config.py                      # LLM config, env vars
│   │
│   ├── agents/
│   │   ├── base_agent.py              # Abstract base class all agents inherit
│   │   ├── fundamentals_analyst.py
│   │   ├── sentiment_analyst.py
│   │   ├── technical_analyst.py
│   │   ├── bull_researcher.py
│   │   ├── bear_researcher.py
│   │   └── portfolio_manager.py
│   │
│   ├── graph/
│   │   └── earnings_graph.py          # LangGraph graph definition
│   │
│   ├── data/
│   │   ├── edgar.py                   # SEC EDGAR transcript fetcher
│   │   └── prices.py                  # yfinance price data fetcher
│   │
│   ├── db/
│   │   ├── models.py                  # SQLAlchemy models
│   │   └── session.py                 # DB session management
│   │
│   ├── backtest/
│   │   ├── runner.py                  # Run pipeline on historical data
│   │   └── reputation.py             # Update agent weights after backtest
│   │
│   └── api/
│       ├── routes/
│       │   ├── analyze.py             # POST /analyze — run on a ticker
│       │   ├── backtest.py            # POST /backtest — run historical eval
│       │   └── predictions.py        # GET /predictions — history
│       └── schemas.py                 # Pydantic request/response schemas
│
└── frontend/
    └── [Next.js app]
        ├── app/
        │   ├── page.tsx               # Main analysis UI
        │   ├── backtest/page.tsx      # Backtest results dashboard
        │   └── history/page.tsx       # Prediction history
        └── components/
            ├── AgentDebate.tsx        # Streamed debate viewer
            ├── ReputationChart.tsx    # Per-agent accuracy over time
            └── PredictionResult.tsx
```

## Environment Variables

```env
# LLM Providers (configure whichever you use)
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
GOOGLE_API_KEY=

# Supabase
SUPABASE_URL=
SUPABASE_PUBLISHABLE_KEY=             # formerly anon key — safe for frontend use
SUPABASE_SECRET_KEY=                  # formerly service_role key — backend only, never expose
DATABASE_URL=                          # postgresql://... (from Supabase connection string)

# App
LLM_PROVIDER=anthropic                 # anthropic | openai | google | ollama
QUICK_MODEL=claude-haiku-4-5-20251001
DEEP_MODEL=claude-sonnet-4-6
MAX_DEBATE_ROUNDS=2
```

---

## Agent Output Contract

Every agent MUST return a JSON object matching its schema. No markdown, no prose — raw JSON only. This is enforced in `base_agent.py`.

```python
# base_agent.py — all agents inherit this
class BaseAgent:
    def analyze(self, context: dict) -> dict:
        raise NotImplementedError
    
    def _call_llm(self, prompt: str, use_deep_model: bool = False) -> dict:
        # Always returns parsed JSON, raises if response is not valid JSON
        pass
```

---

## Conventions

- All LLM calls are async
- Every agent call is logged to the `predictions` table with full JSONB payload
- Never store raw LLM text — always parse to structured JSON before storing
- Debate rounds are configurable via `LLM_CONFIG["max_debate_rounds"]`
- All prices are in USD, all dates are UTC
- Use Pydantic for all API request/response validation
- Environment variables loaded via `python-dotenv`, never hardcoded

---

## Build Order

This is the sequence to follow. Do not skip ahead.

1. **Data pipeline** — `backend/data/edgar.py` and `backend/data/prices.py` working and tested
2. **Database** — schema created, SQLAlchemy models, session management
3. **Single agent** — get FundamentalsAnalyst working end to end with real transcript data
4. **All analysts** — SentimentAnalyst and TechnicalAnalyst following same pattern
5. **Debate loop** — BullResearcher and BearResearcher with configurable rounds
6. **PortfolioManager** — reads all reports, applies equal weights first (reputation comes later)
7. **LangGraph graph** — wire all agents into the graph in `earnings_graph.py`
8. **FastAPI routes** — `/analyze` endpoint that runs the full graph
9. **Backtesting runner** — run pipeline on historical data, store results
10. **Reputation system** — update agent weights based on backtest accuracy
11. **Frontend** — React dashboard, streamed debate viewer, backtest charts
12. **Polish** — README, architecture diagram, deploy

---

## Current Priority

**NEXT: Step 10 — Reputation system**

Steps 1–9 are complete and tested:

**Step 1 — Data pipeline** ✅
- `backend/data/edgar.py` — SEC EDGAR transcript fetcher with retry/backoff
- `backend/data/prices.py` — yfinance price fetcher with 30d direction
- `tests/data/test_edgar.py` + `tests/data/test_prices.py` — 75 tests, all passing

**Step 2 — Database** ✅
- `backend/config.py` — Pydantic BaseSettings loading all env vars
- `backend/db/models.py` — SQLAlchemy 2.x async ORM: Transcript, PriceSnapshot, AgentReputation, Prediction
- `backend/db/session.py` — async engine (asyncpg) + `get_session()` context manager with commit/rollback/close
- `backend/db/init_db.py` — `create_all()` bootstrap script (no Alembic yet)
- `tests/db/test_models.py` + `tests/db/test_session.py` — 34 tests, all passing

**Step 3 — Single Agent (FundamentalsAnalyst)** ✅
- `backend/agents/base_agent.py` — abstract `BaseAgent` with async `_call_llm()`:
  - Routes to anthropic / openai / google / ollama via `settings.llm_provider`
  - `use_deep_model` flag selects between `settings.quick_model` and `settings.deep_model`
  - `_parse_json()` strips markdown fences, raises `ValueError` on non-JSON or non-dict
- `backend/agents/fundamentals_analyst.py` — concrete `FundamentalsAnalyst`:
  - `analyze({"transcript": str}) -> {"signal", "key_points", "confidence"}`
  - Uses quick model; prompt enforces raw JSON only output
- `tests/agents/test_base_agent.py` + `tests/agents/test_fundamentals_analyst.py` — 39 tests, all passing

**Step 4 — All Analysts (SentimentAnalyst + TechnicalAnalyst)** ✅
- `backend/agents/sentiment_analyst.py` — concrete `SentimentAnalyst` inheriting `BaseAgent`:
  - `analyze({"transcript": str}) -> {"signal", "key_points", "confidence"}`
  - Analyzes management tone, language hedging, certainty, Q&A defensiveness
  - Uses quick model; prompt enforces raw JSON only output
- `backend/agents/technical_analyst.py` — concrete `TechnicalAnalyst` inheriting `BaseAgent`:
  - `analyze({"price_data": dict}) -> {"signal", "key_points", "confidence"}`
  - Reads 5d/30d returns, RSI, volume trend, implied move vs historical; formats dict as text in prompt
  - Uses quick model; prompt enforces raw JSON only output
- `tests/agents/test_sentiment_analyst.py` + `tests/agents/test_technical_analyst.py` — 35 tests, all passing

**Step 5 — Debate Loop (BullResearcher + BearResearcher)** ✅
- `backend/agents/bull_researcher.py` — concrete `BullResearcher` inheriting `BaseAgent`:
  - `analyze({"fundamentals", "sentiment", "technical"}) -> {"argument", "confidence", "rebuttals"}`
  - `analyze_rebuttal({...analysts..., "opposing_argument": str}) -> same schema`
  - Uses deep model; both methods enforce raw JSON only output
- `backend/agents/bear_researcher.py` — concrete `BearResearcher` inheriting `BaseAgent`:
  - Same input/output contract as `BullResearcher`; synthesises the bearish case
  - `analyze_rebuttal` feeds the bull's prior argument back as context for the counter-response
- Debate loop pattern: caller alternates `analyze` → `analyze_rebuttal` for `settings.max_debate_rounds` rounds, passing the opponent's last response as `opposing_argument` each time
- `tests/agents/test_bull_researcher.py` + `tests/agents/test_bear_researcher.py` — 52 tests, all passing

**Step 6 — PortfolioManager** ✅
- `backend/agents/portfolio_manager.py` — concrete `PortfolioManager` inheriting `BaseAgent`:
  - `analyze({"fundamentals", "sentiment", "technical", "debate": [{"bull": {...}, "bear": {...}}, ...]}) -> {"direction", "confidence", "reasoning", "weighted_signals"}`
  - Formats debate as multi-round transcript in the prompt
  - Uses deep model; prompt enforces raw JSON only output
  - Equal weights (0.2 each) for all five signal sources; reputation weighting deferred to Step 10
- `tests/agents/test_portfolio_manager.py` — 29 tests, all passing

**Step 7 — LangGraph graph** ✅
- `backend/graph/earnings_graph.py` — LangGraph `StateGraph` wiring all six agents:
  - `PipelineState` TypedDict carries transcript, price_data, fundamentals, sentiment, technical, debate, prediction
  - `analysts` node: FundamentalsAnalyst, SentimentAnalyst, TechnicalAnalyst run concurrently via `asyncio.gather`
  - `debate` node: BullResearcher and BearResearcher run for `settings.max_debate_rounds` rounds; round 0 calls `.analyze()`, rounds 1+ call `.analyze_rebuttal()` with the opponent's prior argument
  - `portfolio_manager` node: reads all accumulated state, writes final prediction
  - `run_pipeline(transcript, price_data, settings?) -> dict` async entry point compiles and invokes the graph
- `tests/graph/test_earnings_graph.py` — 28 tests, all passing

**Step 8 — FastAPI routes** ✅
- `backend/api/schemas.py` — Pydantic request/response models:
  - `AnalyzeRequest`: ticker, transcript, price_data
  - `AnalyzeResponse`: prediction_id (UUID), ticker, run_date, direction, confidence, reasoning, weighted_signals
  - `PredictionRecord`: full row shape with `from_attributes=True` for ORM serialisation
- `backend/api/routes/analyze.py` — `POST /analyze`: calls `run_pipeline`, persists `Prediction` record via `get_session`, returns `AnalyzeResponse` with stored `prediction_id`
- `backend/api/routes/predictions.py` — `GET /predictions`: optional `ticker` and `limit` (default 50) query params; returns `list[PredictionRecord]` ordered by `run_date` desc
- `backend/main.py` — FastAPI app with lifespan placeholder; both routers mounted under `/api/v1`
- `tests/api/test_analyze.py` + `tests/api/test_predictions.py` — 37 tests, all passing

**Step 9 — Backtesting runner** ✅
- `backend/backtest/runner.py` — `run_backtest(tickers, start_date, end_date)` async function:
  - Loads Transcript rows from DB for given tickers and date range
  - Matches each transcript to its PriceSnapshot by (ticker, filing_date)
  - Calls `run_pipeline(transcript_text, price_data)` for each
  - Persists Prediction rows with `actual_direction` and `was_correct` filled in
  - Skips gracefully on missing snapshot, empty/None text, or pipeline exception
  - Returns `BacktestSummary`: `{ total, correct, accuracy, per_ticker }`
- `backend/api/schemas.py` — added `BacktestRequest` (tickers, start_date, end_date), `TickerSummary`, `BacktestResponse`
- `backend/api/routes/backtest.py` — `POST /backtest`: calls `run_backtest`, returns `BacktestResponse`
- `backend/main.py` — backtest router mounted under `/api/v1`
- `tests/backtest/test_runner.py` + `tests/api/test_backtest.py` — 45 tests, all passing

Build the reputation system next:

1. `backend/backtest/reputation.py` — `update_reputation(session)` async function:
   - Reads all `Prediction` rows where `was_correct IS NOT NULL`
   - Groups by the agent signals in `weighted_signals` JSONB to compute per-agent accuracy
   - Upserts `AgentReputation` rows: `correct_predictions`, `total_predictions`, `accuracy`
   - Recomputes normalised `weight` for each agent: `weight = accuracy / sum(all accuracies)`
   - If all accuracies are 0, falls back to equal weights
2. Hook reputation update into the backtest runner — call `update_reputation` at the end of `run_backtest`
3. Unit tests in `tests/backtest/test_reputation.py` — mock DB session; verify upsert logic, weight normalisation, and equal-weight fallback

Update this section at the start of every Claude Code session.