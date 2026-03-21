"""SEC EDGAR transcript fetcher.

Fetches earnings call transcripts from 8-K filings using the EDGAR
full-text search API (EFTS). Returns clean text with metadata.

Usage:
    import asyncio
    from backend.data.edgar import fetch_transcripts

    results = asyncio.run(fetch_transcripts("NVDA", limit=10))
    for r in results:
        print(r.ticker, r.fiscal_quarter, r.word_count)
"""

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# EDGAR requires a descriptive User-Agent with contact info per their access policy:
# https://www.sec.gov/os/accessing-edgar-data
USER_AGENT = "earnings-agent research@earnings-agent.io"

EFTS_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
EDGAR_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

# EDGAR fair access policy: max 10 requests/second
_REQUEST_DELAY = 0.11  # seconds between each outbound request

# Retry configuration for transient HTTP errors
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_MAX_RETRIES = 3
_BASE_RETRY_DELAY = 1.0  # seconds; doubled each attempt (exponential backoff)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class TranscriptResult:
    ticker: str
    company_name: str
    filing_date: date
    fiscal_quarter: Optional[str]  # e.g. "Q3 2024"
    accession_number: str          # e.g. "0001045810-24-000123"
    transcript_text: str
    word_count: int


# ---------------------------------------------------------------------------
# HTML → plain text
# ---------------------------------------------------------------------------


class _HTMLStripper(HTMLParser):
    """Minimal HTML stripper that skips script/style content."""

    _SKIP = {"script", "style", "head"}

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self._SKIP:
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP:
            self._depth = max(0, self._depth - 1)

    def handle_data(self, data: str) -> None:
        if not self._depth:
            self._parts.append(data)

    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self._parts)).strip()


def _strip_html(html: str) -> str:
    stripper = _HTMLStripper()
    try:
        stripper.feed(html)
        return stripper.text()
    except Exception:
        # Crude fallback
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


# ---------------------------------------------------------------------------
# Fiscal quarter inference
# ---------------------------------------------------------------------------


_QUARTER_WORDS = {"first": "Q1", "second": "Q2", "third": "Q3", "fourth": "Q4"}


def _infer_fiscal_quarter(text: str, filing_date: date) -> str:
    """Extract fiscal quarter from transcript text, or infer from filing date."""
    sample = text[:3000]

    # e.g. "Q3 2024"
    m = re.search(r"\b(Q[1-4])\s+(20\d{2})\b", sample, re.IGNORECASE)
    if m:
        return f"{m.group(1).upper()} {m.group(2)}"

    # e.g. "third quarter 2024"
    m = re.search(
        r"\b(first|second|third|fourth)\s+quarter\b.{0,40}(20\d{2})",
        sample,
        re.IGNORECASE,
    )
    if m:
        q = _QUARTER_WORDS.get(m.group(1).lower())
        if q:
            return f"{q} {m.group(2)}"

    # Fall back to filing date
    q_num = (filing_date.month - 1) // 3 + 1
    return f"Q{q_num} {filing_date.year}"


# ---------------------------------------------------------------------------
# HTTP with retry
# ---------------------------------------------------------------------------


async def _retrying_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_retries: int = _MAX_RETRIES,
    base_delay: float = _BASE_RETRY_DELAY,
    **kwargs,
):
    """GET with exponential backoff on 429 and transient 5xx errors.

    Non-retryable 4xx responses (400, 403, 404, …) raise immediately.
    After exhausting all retries the last error response is raised.
    """
    resp = None
    for attempt in range(max_retries + 1):
        resp = await client.get(url, **kwargs)
        if resp.status_code not in _RETRYABLE_STATUS_CODES:
            resp.raise_for_status()
            return resp

        if attempt < max_retries:
            delay = base_delay * (2 ** attempt)
            logger.warning(
                "HTTP %s on attempt %d/%d for %s — retrying in %.1fs",
                resp.status_code,
                attempt + 1,
                max_retries + 1,
                url,
                delay,
            )
            await asyncio.sleep(delay)

    # All retries exhausted — surface the last error response
    resp.raise_for_status()


# ---------------------------------------------------------------------------
# CIK resolution
# ---------------------------------------------------------------------------


async def _resolve_cik(ticker: str, client: httpx.AsyncClient) -> str:
    """Return the zero-padded 10-digit CIK for a ticker symbol.

    Raises:
        ValueError: If the ticker cannot be found in EDGAR's company list.
    """
    resp = await _retrying_get(client, COMPANY_TICKERS_URL)
    tickers_map = resp.json()

    upper = ticker.upper()
    for entry in tickers_map.values():
        if entry.get("ticker", "").upper() == upper:
            cik = str(entry["cik_str"]).zfill(10)
            logger.debug("Resolved %s → CIK %s", ticker, cik)
            return cik

    raise ValueError(
        f"Ticker '{ticker}' not found in SEC EDGAR company list. "
        "Verify the symbol is a US-listed equity."
    )


# ---------------------------------------------------------------------------
# EFTS full-text search
# ---------------------------------------------------------------------------


async def _search_efts(
    ticker: str,
    client: httpx.AsyncClient,
    fetch_size: int,
) -> list[dict]:
    """Query EDGAR EFTS for 8-K filings mentioning 'earnings call'."""
    params = {
        "q": '"earnings call"',
        "forms": "8-K",
        "entity": ticker,
        "dateRange": "custom",
        "startdt": "2010-01-01",
        "enddt": datetime.now(UTC).strftime("%Y-%m-%d"),
        "_source": "period_of_report,entity_name,file_date,accession_no,display_names",
        "from": 0,
        "size": fetch_size,
    }
    await asyncio.sleep(_REQUEST_DELAY)
    resp = await _retrying_get(client, EFTS_SEARCH_URL, params=params)
    hits = resp.json().get("hits", {}).get("hits", [])
    logger.info("EFTS returned %d hits for '%s'", len(hits), ticker)
    return hits


# ---------------------------------------------------------------------------
# Filing document retrieval
# ---------------------------------------------------------------------------


async def _get_document_url(
    cik: str,
    accession_number: str,
    client: httpx.AsyncClient,
) -> Optional[str]:
    """Fetch the filing index JSON and return the best document URL.

    Prefers EX-99.1 exhibits (typical for transcripts), then falls back to
    the primary document (sequence 1), then the first document.
    """
    cik_int = str(int(cik))           # strip leading zeros for archive path
    acc_nodash = accession_number.replace("-", "")
    index_url = (
        f"{EDGAR_ARCHIVES}/{cik_int}/{acc_nodash}/{accession_number}-index.json"
    )

    await asyncio.sleep(_REQUEST_DELAY)
    try:
        resp = await _retrying_get(client, index_url)
        documents: list[dict] = resp.json().get("documents", [])
    except httpx.HTTPStatusError as exc:
        logger.warning("Filing index HTTP %s for %s/%s", exc.response.status_code, cik, accession_number)
        return None
    except Exception as exc:
        logger.warning("Filing index fetch error for %s/%s: %s", cik, accession_number, exc)
        return None

    if not documents:
        return None

    # Score documents: EX-99.1 > primary > first
    exhibit = None
    primary = None
    for doc in documents:
        doc_type = doc.get("type", "")
        filename = doc.get("filename", "").lower()
        is_exhibit = "99.1" in doc_type or "ex99" in filename or "ex-99" in filename
        is_primary = doc.get("sequence") == "1" or doc.get("sequence") == 1

        if is_exhibit and exhibit is None:
            exhibit = doc
        if is_primary and primary is None:
            primary = doc

    chosen = exhibit or primary or documents[0]
    filename = chosen.get("filename", "")
    if not filename:
        return None

    return f"{EDGAR_ARCHIVES}/{cik_int}/{acc_nodash}/{filename}"


async def _fetch_document_text(url: str, client: httpx.AsyncClient) -> Optional[str]:
    """Fetch a filing document and return clean plain text, or None if unusable."""
    await asyncio.sleep(_REQUEST_DELAY)
    try:
        resp = await _retrying_get(client, url)
    except Exception as exc:
        logger.warning("Document fetch failed for %s: %s", url, exc)
        return None

    raw = resp.text
    content_type = resp.headers.get("content-type", "")

    if "html" in content_type or url.lower().endswith((".htm", ".html")):
        text = _strip_html(raw)
    elif url.lower().endswith(".txt"):
        # Full-submission .txt files have SGML wrappers; strip them too
        start = raw.find("<DOCUMENT>")
        text = _strip_html(raw[start:] if start != -1 else raw)
    else:
        text = _strip_html(raw)

    # Reject documents that are too short to be a real transcript
    if len(text.split()) < 300:
        return None

    return text


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def fetch_transcripts(ticker: str, limit: int = 10) -> list[TranscriptResult]:
    """Fetch the most recent earnings call transcripts for a ticker from SEC EDGAR.

    Searches 8-K filings for documents mentioning "earnings call", fetches each
    filing document, strips HTML, and returns structured results sorted
    newest-first.

    Args:
        ticker: US equity ticker symbol (e.g. "NVDA", "AAPL").
        limit:  Maximum number of transcripts to return (default 10).

    Returns:
        List of TranscriptResult, sorted by filing_date descending.

    Raises:
        ValueError: If the ticker cannot be resolved to a CIK.
        httpx.HTTPError: On unrecoverable network errors.
    """
    headers = {
        "User-Agent": USER_AGENT,
        "Accept-Encoding": "gzip, deflate",
    }

    async with httpx.AsyncClient(
        headers=headers,
        timeout=httpx.Timeout(30.0, connect=10.0),
        follow_redirects=True,
    ) as client:
        # Step 1: ticker → CIK
        cik = await _resolve_cik(ticker, client)

        # Step 2: search EFTS — over-fetch to account for documents that turn
        # out to be unusable (too short, wrong exhibit, etc.)
        fetch_size = min(limit * 4, 40)
        hits = await _search_efts(ticker, client, fetch_size)

        if not hits:
            logger.warning("No EFTS results found for '%s'", ticker)
            return []

        # Step 3: for each hit, resolve and fetch the document
        results: list[TranscriptResult] = []

        for hit in hits:
            if len(results) >= limit:
                break

            source = hit.get("_source", {})
            accession_number = source.get("accession_no", "").strip()
            if not accession_number:
                continue

            filing_date_str = source.get("file_date", "")
            try:
                filing_date = datetime.strptime(filing_date_str, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                filing_date = date.today()

            raw_name = source.get("entity_name", ticker)
            company_name = raw_name[0] if isinstance(raw_name, list) else raw_name

            doc_url = await _get_document_url(cik, accession_number, client)
            if not doc_url:
                logger.debug("No usable document URL for %s / %s", ticker, accession_number)
                continue

            text = await _fetch_document_text(doc_url, client)
            if not text:
                logger.debug("Document too short or empty for %s / %s", ticker, accession_number)
                continue

            fiscal_quarter = _infer_fiscal_quarter(text, filing_date)

            results.append(
                TranscriptResult(
                    ticker=ticker.upper(),
                    company_name=company_name,
                    filing_date=filing_date,
                    fiscal_quarter=fiscal_quarter,
                    accession_number=accession_number,
                    transcript_text=text,
                    word_count=len(text.split()),
                )
            )
            logger.info(
                "Fetched %s %s (%d words) from %s",
                ticker.upper(),
                fiscal_quarter,
                len(text.split()),
                filing_date,
            )

        # Newest first
        results.sort(key=lambda r: r.filing_date, reverse=True)
        return results[:limit]
