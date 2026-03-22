# earnings-agent

A multi-agent LLM framework that analyzes earnings call transcripts to predict post-earnings stock price direction. Specialized AI agents with distinct analytical roles read the same transcript, form independent views, and debate each other before a portfolio manager makes a final prediction.

**Novel contribution:** a **reputation-weighted decision system** where each agent accumulates an accuracy score over historical backtests and their influence on the final prediction is weighted proportionally to their track record. Agents that are consistently right carry more weight — the system learns which analytical lens is most predictive over time.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Data Layer                                                     │
│  SEC EDGAR API ──► transcript text                              │
│  yfinance      ──► historical price data                        │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│  Agent Pipeline (LangGraph StateGraph)                          │
│                                                                 │
│  ┌─────────────────────────────────────────┐                   │
│  │  Analyst Team (parallel)                │                   │
│  │  ├── FundamentalsAnalyst                │                   │
│  │  │     revenue, EPS, margins, guidance  │                   │
│  │  ├── SentimentAnalyst                   │                   │
│  │  │     tone, hedging, Q&A confidence    │                   │
│  │  └── TechnicalAnalyst                   │                   │
│  │        5d/30d returns, RSI, volume      │                   │
│  └─────────────────────────────────────────┘                   │
│                          │                                      │
│  ┌─────────────────────────────────────────┐                   │
│  │  Researcher Team (sequential debate)    │                   │
│  │  ├── BullResearcher  ◄──────────────►  │                   │
│  │  └── BearResearcher   N debate rounds   │                   │
│  └─────────────────────────────────────────┘                   │
│                          │                                      │
│  ┌─────────────────────────────────────────┐                   │
│  │  PortfolioManager                       │                   │
│  │  applies reputation weights → prediction│                   │
│  └─────────────────────────────────────────┘                   │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│  Output: { direction, confidence, reasoning, agent_reports }    │
│  Stored in PostgreSQL (Supabase)                                │
└───────────────┬─────────────────────────────────────────────────┘
                │                         ▲
                ▼                         │
┌──────────────────────────┐   ┌──────────┴──────────────────────┐
│  FastAPI (3 routes)      │   │  Backtesting + Reputation Loop  │
│  POST /analyze           │   │  ├── run pipeline on history     │
│  GET  /predictions       │   │  ├── compare to actual price     │
│  POST /ingest            │   │  └── update agent weights in DB  │
│  POST /backtest          │   └─────────────────────────────────┘
└──────────────┬───────────┘   └─────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────┐
│  Frontend (Next.js)                          │
│  ├── Analyze  — run pipeline on any transcript  │
│  ├── History  — past predictions with debate    │
│  ├── Ingest   — paste transcripts into DB       │
│  └── Backtest — reputation chart by agent       │
└──────────────────────────────────────────────┘
```

See [docs/architecture.md](docs/architecture.md) for a detailed Mermaid diagram including the reputation feedback loop.

---

## Quickstart

### Prerequisites

- Python 3.11+
- Node.js 20+
- A [Supabase](https://supabase.com) project (free tier works)
- At least one LLM provider API key (Anthropic, OpenAI, or Google)

### 1. Clone and configure

```bash
git clone https://github.com/your-org/earnings-agent.git
cd earnings-agent
cp .env.example .env
# Fill in .env with your API keys and Supabase connection string
```

### 2. Run the backend

```bash
pip install -e ".[dev]"
uvicorn backend.main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

### 3. Initialize the database

```bash
python -m backend.db.init_db
```

This runs `create_all()` against your Supabase PostgreSQL instance.

### 4. Run the frontend

```bash
cd frontend
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

The dashboard will be available at `http://localhost:3000`.

### Docker (backend + frontend together)

```bash
cp .env.example .env
# fill in .env
docker compose up --build
```

Backend: `http://localhost:8000` | Frontend: `http://localhost:3000`

---

## API Reference

### `POST /api/v1/analyze`

Run the full agent pipeline on a transcript.

**Request**
```json
{
  "ticker": "AAPL",
  "transcript": "Good morning. Revenue grew 12% year-over-year...",
  "price_data": {
    "return_5d": 0.023,
    "return_30d": -0.041,
    "rsi_14": 58.3,
    "volume_trend": "increasing",
    "implied_move": 0.05,
    "historical_move_avg": 0.038
  }
}
```

**Response**
```json
{
  "prediction_id": "3f2a1b4c-...",
  "ticker": "AAPL",
  "run_date": "2026-03-21T14:32:00Z",
  "direction": "up",
  "confidence": 0.74,
  "reasoning": "Strong revenue beat with improving margins offset by cautious guidance. Bull case carried more weight given technical momentum.",
  "weighted_signals": {
    "fundamentals": { "signal": "bullish", "weight": 0.22 },
    "sentiment":    { "signal": "neutral",  "weight": 0.19 },
    "technical":    { "signal": "bullish", "weight": 0.21 },
    "bull":         { "signal": "bullish", "weight": 0.20 },
    "bear":         { "signal": "bearish", "weight": 0.18 }
  }
}
```

---

### `GET /api/v1/predictions`

Retrieve prediction history.

**Query params**
| Param    | Type   | Default | Description                     |
|----------|--------|---------|---------------------------------|
| `ticker` | string | —       | Filter by ticker symbol         |
| `limit`  | int    | 50      | Max records to return           |

**Response** — array of prediction records ordered by `run_date` descending:
```json
[
  {
    "id": "3f2a1b4c-...",
    "ticker": "AAPL",
    "run_date": "2026-03-21T14:32:00Z",
    "final_direction": "up",
    "final_confidence": 0.74,
    "final_reasoning": "...",
    "agent_reports": { ... },
    "debate_transcript": { ... },
    "weighted_signals": { ... },
    "actual_direction": "up",
    "was_correct": true
  }
]
```

---

### `POST /api/v1/ingest`

Store a manually pasted transcript in the backtest database. The price snapshot for the earnings date is fetched automatically via yfinance.

**Request**
```json
{
  "ticker": "AAPL",
  "fiscal_quarter": "Q1 2025",
  "filing_date": "2025-01-30",
  "transcript_text": "Good morning and welcome to Apple's Q1 2025 earnings call..."
}
```

**Response**
```json
{
  "transcript_id": "a1b2c3d4-...",
  "ticker": "AAPL",
  "fiscal_quarter": "Q1 2025",
  "filing_date": "2025-01-30",
  "word_count": 12847,
  "price_snapshot_found": true,
  "actual_direction": "up"
}
```

> **Why this exists:** FMP deprecated free-tier transcript API access in August 2025. SEC EDGAR does not carry transcripts for large-cap companies. The ingest route lets you paste transcripts from any public source (e.g. [Motley Fool](https://www.fool.com/earnings-call-transcripts/)) to seed the backtest database without a paid subscription.

---

### `POST /api/v1/backtest`

Run the pipeline on historical earnings data and evaluate accuracy.

**Request**
```json
{
  "tickers": ["AAPL", "MSFT", "NVDA"],
  "start_date": "2024-01-01",
  "end_date":   "2024-12-31"
}
```

**Response**
```json
{
  "total": 12,
  "correct": 8,
  "accuracy": 0.667,
  "per_ticker": {
    "AAPL": { "total": 4, "correct": 3, "accuracy": 0.75 },
    "MSFT": { "total": 4, "correct": 3, "accuracy": 0.75 },
    "NVDA": { "total": 4, "correct": 2, "accuracy": 0.50 }
  }
}
```

After the run completes, agent reputation weights are automatically updated in the database.

---

## How Backtesting and Reputation Weighting Work

### Backtesting

1. Load transcript rows from the database for the given tickers and date range.
2. Match each transcript to its `PriceSnapshot` row (ticker + filing date).
3. Run the full agent pipeline on each transcript.
4. Compare the predicted direction to `actual_direction` (price 30 days post-earnings).
5. Persist `was_correct` on the `Prediction` row.

### Reputation update

After each backtest run, `update_reputation()` is called automatically:

1. Read all resolved predictions (`was_correct IS NOT NULL`).
2. Map each agent's signal (bullish/bearish/neutral → up/down/neutral).
3. Tally per-agent `correct_predictions` / `total_predictions`.
4. Upsert `AgentReputation` rows with updated accuracy.
5. Recompute normalized weights: `weight = agent_accuracy / sum(all_agent_accuracies)`.
6. Fall back to equal weights (0.2 each) if all agents have zero accuracy.

The `PortfolioManager` reads these weights from the database at runtime and applies them when synthesizing the final prediction — so the system gradually shifts influence toward the agents with the strongest track record.

---

## Tech Stack

| Layer              | Technology                                          |
|--------------------|-----------------------------------------------------|
| Agent orchestration| LangGraph                                           |
| LLM providers      | Anthropic Claude, OpenAI GPT, Google Gemini, Ollama |
| Quick tasks        | `claude-haiku-4-5` / `gpt-4o-mini`                 |
| Deep reasoning     | `claude-sonnet-4-6` / `gpt-4o`                     |
| Backend API        | Python, FastAPI, Uvicorn                            |
| Database           | PostgreSQL via Supabase (hosted)                    |
| Transcript data    | Manual ingestion UI + SEC EDGAR submissions API (fallback) |
| Price data         | yfinance (free Python library)                      |
| Frontend           | React 19, Next.js 16, TypeScript, Tailwind CSS      |
| Charts             | Recharts                                            |

---

## Deployment

### Railway (recommended)

1. Fork this repo and connect it to [Railway](https://railway.app).
2. Create two services: one pointing at the repo root (backend) and one at `frontend/`.
3. Set all environment variables from `.env.example` in the Railway dashboard.
4. Railway auto-detects the `Dockerfile` for each service.

**Backend start command:** `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`

**Frontend environment variable:** `NEXT_PUBLIC_API_URL=https://your-backend.railway.app/api/v1`

### Render

1. Create a new **Web Service** for the backend, set root to `/`, build command `pip install -e .`, start command `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`.
2. Create a second **Web Service** for the frontend, set root to `/frontend`, build command `npm install && npm run build`, start command `npm start`.
3. Set `NEXT_PUBLIC_API_URL=https://your-backend.onrender.com/api/v1` on the frontend service.

### Vercel (frontend only)

```bash
cd frontend
npx vercel --env NEXT_PUBLIC_API_URL=https://your-backend-url.com/api/v1
```

---

## Environment Variables

Copy `.env.example` to `.env` and fill in:

```env
# LLM Providers — configure whichever you use
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
GOOGLE_API_KEY=

# Supabase
SUPABASE_URL=
SUPABASE_PUBLISHABLE_KEY=    # anon key — safe for frontend use
SUPABASE_SECRET_KEY=         # service_role key — backend only, never expose
DATABASE_URL=                 # postgresql://... (Supabase connection string)

# App
LLM_PROVIDER=anthropic       # anthropic | openai | google | ollama
QUICK_MODEL=claude-haiku-4-5-20251001
DEEP_MODEL=claude-sonnet-4-6
MAX_DEBATE_ROUNDS=2
```

---

## Project Structure

```
earnings-agent/
├── backend/
│   ├── agents/          # Six agent implementations + base class
│   ├── api/             # FastAPI routes + Pydantic schemas
│   ├── backtest/        # Runner + reputation updater
│   ├── data/            # SEC EDGAR + yfinance fetchers
│   ├── db/              # SQLAlchemy models + session management
│   ├── graph/           # LangGraph StateGraph wiring all agents
│   ├── config.py        # LLM config + env var loading
│   └── main.py          # FastAPI app entry point
├── frontend/
│   ├── app/             # Next.js App Router pages
│   └── components/      # AgentDebate, PredictionResult, ReputationChart
├── docs/
│   └── architecture.md  # Mermaid architecture diagram
├── tests/               # pytest test suite (250+ tests)
├── docker-compose.yml
├── pyproject.toml
└── .env.example
```
