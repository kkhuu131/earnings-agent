"""SEC EDGAR transcript fetcher.

Fetches earnings call transcripts from 8-K filings using the EDGAR
submissions API. Returns clean text with metadata.

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

SUBMISSIONS_URL = "https://data.sec.gov/submissions"
EDGAR_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

# EDGAR fair access policy: max 10 requests/second, but Archives is more
# sensitive — use a conservative 0.5s to avoid 503s from that endpoint
_REQUEST_DELAY = 0.5  # seconds between each outbound request

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
# Submissions API — filing list
# ---------------------------------------------------------------------------


async def _fetch_submissions(cik: str, client: httpx.AsyncClient) -> list[dict]:
    """Fetch all filings for a company from the EDGAR submissions API.

    The submissions JSON contains parallel arrays under filings.recent. There
    may also be additional paginated files listed under filings.files — each is
    fetched and merged in.

    Args:
        cik: Zero-padded 10-digit CIK string (e.g. "0001045810").
        client: Shared httpx.AsyncClient.

    Returns:
        List of filing dicts, each with keys: accessionNumber, filingDate,
        form, primaryDocument, items.
    """
    url = f"{SUBMISSIONS_URL}/CIK{cik}.json"
    await asyncio.sleep(_REQUEST_DELAY)
    resp = await _retrying_get(client, url)
    data = resp.json()

    company_name: str = data.get("name", "")
    filings_block = data.get("filings", {})

    def _zip_recent(recent: dict) -> list[dict]:
        """Zip parallel arrays in a filings.recent block into a list of dicts."""
        acc_nums = recent.get("accessionNumber", [])
        filing_dates = recent.get("filingDate", [])
        forms = recent.get("form", [])
        primary_docs = recent.get("primaryDocument", [])
        items_list = recent.get("items", [])

        results = []
        for i, acc in enumerate(acc_nums):
            results.append({
                "accessionNumber": acc,
                "filingDate": filing_dates[i] if i < len(filing_dates) else "",
                "form": forms[i] if i < len(forms) else "",
                "primaryDocument": primary_docs[i] if i < len(primary_docs) else "",
                "items": items_list[i] if i < len(items_list) else "",
                "companyName": company_name,
            })
        return results

    all_filings = _zip_recent(filings_block.get("recent", {}))

    # Follow paginated filing pages if present
    for page_ref in filings_block.get("files", []):
        page_name = page_ref.get("name", "")
        if not page_name:
            continue
        page_url = f"{SUBMISSIONS_URL}/{page_name}"
        await asyncio.sleep(_REQUEST_DELAY)
        try:
            page_resp = await _retrying_get(client, page_url)
            page_data = page_resp.json()
            all_filings.extend(_zip_recent(page_data))
        except Exception as exc:
            logger.warning("Failed to fetch submissions page %s: %s", page_url, exc)

    return all_filings


# ---------------------------------------------------------------------------
# Filing document retrieval
# ---------------------------------------------------------------------------


async def _get_document_url(
    cik: str,
    accession_number: str,
    client: httpx.AsyncClient,
) -> Optional[str]:
    """Fetch the filing index JSON and return the best document URL.

    Prefers EX-99.2 exhibits (standard slot for transcripts), then EX-99.1
    (press release / earnings release), then falls back to the primary
    document (sequence 1), then the first document.
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

    # Score documents: EX-99.2 (transcript) > EX-99.1 (press release) > primary > first
    exhibit_992 = None
    exhibit_991 = None
    primary = None
    for doc in documents:
        doc_type = doc.get("type", "")
        filename = doc.get("filename", "").lower()
        is_992 = "99.2" in doc_type or "ex99.2" in filename or "ex-99.2" in filename
        is_991 = (
            "99.1" in doc_type
            or "ex99.1" in filename
            or "ex-99.1" in filename
            # Catch legacy naming patterns like ex991.htm (no separator)
            or (("ex99" in filename or "ex-99" in filename) and "99.2" not in doc_type)
        )
        is_primary = doc.get("sequence") == "1" or doc.get("sequence") == 1

        if is_992 and exhibit_992 is None:
            exhibit_992 = doc
        if is_991 and exhibit_991 is None:
            exhibit_991 = doc
        if is_primary and primary is None:
            primary = doc

    chosen = exhibit_992 or exhibit_991 or primary or documents[0]
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

    # Reject documents that are too short to be a real transcript.
    # Press releases are typically 500–2 000 words; transcripts are 5 000–15 000.
    if len(text.split()) < 2000:
        return None

    return text


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def fetch_transcripts(ticker: str, limit: int = 10) -> list[TranscriptResult]:
    """Fetch the most recent earnings call transcripts for a ticker from SEC EDGAR.

    Uses the EDGAR submissions API to find 8-K filings with item 2.02
    (Results of Operations), which is the standard item code for earnings
    results filings. Fetches each filing's exhibit document, strips HTML,
    and returns structured results sorted newest-first.

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
        company_name = ticker.upper()  # fallback; overwritten from submissions data

        # Step 2: fetch the company's full filing list from the submissions API
        all_filings = await _fetch_submissions(cik, client)

        # Update company_name from the first filing that has it
        for filing in all_filings:
            if filing.get("companyName"):
                company_name = filing["companyName"]
                break

        # Step 3: filter to 8-K filings containing item 2.02
        # (Results of Operations — standard item for earnings results)
        candidates = []
        for filing in all_filings:
            if filing.get("form") != "8-K":
                continue
            items_str = filing.get("items", "") or ""
            item_codes = [i.strip() for i in items_str.split(",")]
            if "2.02" not in item_codes:
                continue
            candidates.append(filing)

        # Step 4: sort newest first
        def _parse_date(s: str) -> date:
            try:
                return datetime.strptime(s, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                return date.min

        candidates.sort(key=lambda f: _parse_date(f.get("filingDate", "")), reverse=True)

        # Step 5: over-fetch candidates to account for press releases without transcripts
        fetch_limit = min(limit * 10, len(candidates))
        results: list[TranscriptResult] = []

        for filing in candidates[:fetch_limit]:
            if len(results) >= limit:
                break

            accession_number = filing.get("accessionNumber", "").strip()
            if not accession_number:
                continue

            filing_date = _parse_date(filing.get("filingDate", ""))
            if filing_date == date.min:
                filing_date = date.today()

            doc_url = await _get_document_url(cik, accession_number, client)
            if not doc_url:
                # Filing index unavailable (404/503) — fall back to the primaryDocument
                # filename already known from the submissions API.
                primary_doc = filing.get("primaryDocument", "")
                if primary_doc:
                    cik_int = str(int(cik))
                    acc_nodash = accession_number.replace("-", "")
                    doc_url = f"{EDGAR_ARCHIVES}/{cik_int}/{acc_nodash}/{primary_doc}"
                    logger.debug("Index unavailable for %s/%s — trying primary doc: %s", ticker, accession_number, primary_doc)
                else:
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

        # Newest first (candidates are already sorted, but enforce after any ties)
        results.sort(key=lambda r: r.filing_date, reverse=True)
        return results[:limit]
