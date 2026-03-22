"""Transcript coverage recon script.

Checks both FMP and EDGAR to find which tickers have transcript coverage.
Run from the repo root:

    python scripts/recon.py

Requires FMP_API_KEY in .env for FMP checks. EDGAR is checked regardless.
"""

import asyncio
import logging

from backend.config import settings
from backend.data.edgar import fetch_transcripts as edgar_fetch
from backend.data.fmp import fetch_transcripts as fmp_fetch

logging.basicConfig(level=logging.ERROR)  # suppress httpx + EDGAR 404 noise

TICKERS = [
    # Large-cap (FMP covers these; EDGAR usually doesn't have transcripts)
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA",
    # Financials
    "JPM", "BAC", "GS", "MS", "WFC",
    # Other sectors
    "UNH", "LMT", "CAT", "AMD", "QCOM",
    # Mid-cap / growth (EDGAR more likely to have coverage)
    "CRWD", "ZS", "SNOW", "DDOG", "MDB",
]


async def check_ticker(ticker: str, fmp_key: str) -> dict:
    fmp_count, fmp_quarters = 0, []
    edgar_count, edgar_quarters = 0, []

    if fmp_key:
        try:
            results = await fmp_fetch(ticker, api_key=fmp_key, limit=3)
            fmp_count = len(results)
            fmp_quarters = [r.fiscal_quarter for r in results]
        except Exception as exc:
            fmp_quarters = [f"ERR: {exc}"]

    try:
        results = await edgar_fetch(ticker, limit=3)
        edgar_count = len(results)
        edgar_quarters = [r.fiscal_quarter for r in results]
    except Exception as exc:
        edgar_quarters = [f"ERR: {exc}"]

    return {
        "ticker": ticker,
        "fmp": fmp_count,
        "fmp_quarters": fmp_quarters,
        "edgar": edgar_count,
        "edgar_quarters": edgar_quarters,
    }


async def recon():
    fmp_key = settings.fmp_api_key
    if not fmp_key:
        print("WARNING: FMP_API_KEY not set in .env — FMP column will show 0 for all tickers.\n")

    # Run checks sequentially to avoid hammering APIs
    rows = []
    for ticker in TICKERS:
        row = await check_ticker(ticker, fmp_key)
        rows.append(row)

    # Print results
    fmp_col = "FMP" if fmp_key else "FMP (no key)"
    print(f"\n{'Ticker':<8}  {fmp_col:<6}  {'EDGAR':<6}  Best source / quarters")
    print("─" * 70)

    for r in sorted(rows, key=lambda x: -(x["fmp"] + x["edgar"])):
        ticker = r["ticker"]
        fmp_n = r["fmp"]
        edgar_n = r["edgar"]

        if fmp_n > 0:
            source = f"FMP  {', '.join(r['fmp_quarters'])}"
        elif edgar_n > 0:
            source = f"EDGAR  {', '.join(r['edgar_quarters'])}"
        else:
            source = "—  no coverage"

        print(f"{ticker:<8}  {fmp_n:<6}  {edgar_n:<6}  {source}")

    fmp_tickers = [r["ticker"] for r in rows if r["fmp"] > 0]
    edgar_only  = [r["ticker"] for r in rows if r["fmp"] == 0 and r["edgar"] > 0]
    none_tickers = [r["ticker"] for r in rows if r["fmp"] == 0 and r["edgar"] == 0]

    print(f"\nFMP coverage ({len(fmp_tickers)}):         {', '.join(fmp_tickers) or '—'}")
    print(f"EDGAR only  ({len(edgar_only)}):         {', '.join(edgar_only) or '—'}")
    print(f"No coverage ({len(none_tickers)}):         {', '.join(none_tickers) or '—'}")
    print("\nAdd tickers with coverage to TICKERS in scripts/populate_db.py")


if __name__ == "__main__":
    asyncio.run(recon())
