"""Unit tests for backend/data/edgar.py.

All HTTP calls are intercepted by MockAsyncClient / MockResponse so no
network access is required.  asyncio.sleep is patched to a no-op so tests
run at full speed.
"""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.data.edgar import (
    _BASE_RETRY_DELAY,
    _MAX_RETRIES,
    COMPANY_TICKERS_URL,
    EDGAR_ARCHIVES,
    EFTS_SEARCH_URL,
    TranscriptResult,
    _fetch_document_text,
    _get_document_url,
    _infer_fiscal_quarter,
    _resolve_cik,
    _retrying_get,
    _search_efts,
    _strip_html,
    fetch_transcripts,
)
from tests.conftest import MockAsyncClient, MockResponse

# ---------------------------------------------------------------------------
# Shared sample data
# ---------------------------------------------------------------------------

_COMPANY_TICKERS = {
    "0": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA Corp"},
    "1": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc"},
}

_EFTS_RESPONSE = {
    "hits": {
        "total": {"value": 2},
        "hits": [
            {
                "_id": "hit1",
                "_source": {
                    "accession_no": "0001045810-24-000123",
                    "file_date": "2024-05-22",
                    "entity_name": "NVIDIA Corp",
                    "period_of_report": "2024-04-28",
                },
            },
            {
                "_id": "hit2",
                "_source": {
                    "accession_no": "0001045810-23-000456",
                    "file_date": "2023-08-23",
                    "entity_name": "NVIDIA Corp",
                    "period_of_report": "2023-07-26",
                },
            },
        ],
    }
}

_FILING_INDEX_WITH_EXHIBIT = {
    "documents": [
        {"filename": "form8k.htm", "type": "8-K", "sequence": "1", "description": "Form 8-K"},
        {"filename": "ex991.htm", "type": "EX-99.1", "sequence": "2", "description": "Earnings Call"},
    ]
}

_FILING_INDEX_PRIMARY_ONLY = {
    "documents": [
        {"filename": "primary.htm", "type": "8-K", "sequence": "1", "description": "Form 8-K"},
    ]
}

_FILING_INDEX_EMPTY = {"documents": []}

# A document long enough to pass the 300-word minimum check
_TRANSCRIPT_WORDS = " ".join(f"wordtoken{i}" for i in range(350))
_TRANSCRIPT_HTML = f"<html><head><style>body{{}}</style></head><body><p>{_TRANSCRIPT_WORDS}</p></body></html>"


# ---------------------------------------------------------------------------
# Autouse fixture: eliminate asyncio.sleep latency in all tests in this module
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
async def _no_sleep(monkeypatch):
    """Patch asyncio.sleep to a no-op and yield the mock for call assertions."""
    mock = AsyncMock()
    monkeypatch.setattr("backend.data.edgar.asyncio.sleep", mock)
    yield mock


# ---------------------------------------------------------------------------
# _strip_html
# ---------------------------------------------------------------------------


class TestStripHtml:
    def test_removes_basic_tags(self):
        assert _strip_html("<p>Hello <b>world</b></p>") == "Hello world"

    def test_removes_nested_tags(self):
        result = _strip_html("<div><span><em>text</em></span></div>")
        assert result == "text"

    def test_collapses_whitespace(self):
        result = _strip_html("<p>a</p>   <p>b</p>")
        assert "  " not in result
        assert "a" in result and "b" in result

    def test_excludes_script_content(self):
        result = _strip_html("<body><script>alert('xss')</script><p>safe</p></body>")
        assert "alert" not in result
        assert "safe" in result

    def test_excludes_style_content(self):
        result = _strip_html("<head><style>body { color: red; }</style></head><body>text</body>")
        assert "color" not in result
        assert "text" in result

    def test_empty_string(self):
        assert _strip_html("") == ""

    def test_plain_text_passthrough(self):
        assert _strip_html("no tags here") == "no tags here"


# ---------------------------------------------------------------------------
# _infer_fiscal_quarter
# ---------------------------------------------------------------------------


class TestInferFiscalQuarter:
    def test_extracts_q_number_format(self):
        assert _infer_fiscal_quarter("Q3 2024 results", date(2024, 10, 1)) == "Q3 2024"

    def test_extracts_q_number_case_insensitive(self):
        assert _infer_fiscal_quarter("q1 2023 earnings", date(2023, 4, 1)) == "Q1 2023"

    def test_extracts_word_quarter_third(self):
        result = _infer_fiscal_quarter("third quarter 2023 was strong", date(2023, 10, 1))
        assert result == "Q3 2023"

    def test_extracts_word_quarter_first(self):
        result = _infer_fiscal_quarter("first quarter 2022 highlights", date(2022, 4, 1))
        assert result == "Q1 2022"

    @pytest.mark.parametrize("month,expected_q", [(1, "Q1"), (4, "Q2"), (7, "Q3"), (10, "Q4")])
    def test_fallback_inferred_from_filing_month(self, month, expected_q):
        result = _infer_fiscal_quarter("no quarter info here", date(2024, month, 15))
        assert result == f"{expected_q} 2024"

    def test_q_number_takes_priority_over_fallback(self):
        # Even if filing date implies Q4, the text Q1 should win
        result = _infer_fiscal_quarter("Q1 2024 discussion", date(2024, 11, 1))
        assert result == "Q1 2024"


# ---------------------------------------------------------------------------
# _resolve_cik
# ---------------------------------------------------------------------------


class TestResolveCik:
    async def test_returns_zero_padded_cik(self):
        client = MockAsyncClient([
            (COMPANY_TICKERS_URL, MockResponse(json_data=_COMPANY_TICKERS)),
        ])
        cik = await _resolve_cik("NVDA", client)
        assert cik == "0001045810"

    async def test_case_insensitive_ticker(self):
        client = MockAsyncClient([
            (COMPANY_TICKERS_URL, MockResponse(json_data=_COMPANY_TICKERS)),
        ])
        cik = await _resolve_cik("nvda", client)
        assert cik == "0001045810"

    async def test_raises_for_unknown_ticker(self):
        client = MockAsyncClient([
            (COMPANY_TICKERS_URL, MockResponse(json_data=_COMPANY_TICKERS)),
        ])
        with pytest.raises(ValueError, match="FAKE"):
            await _resolve_cik("FAKE", client)

    async def test_raises_on_http_error(self):
        client = MockAsyncClient([
            (COMPANY_TICKERS_URL, httpx.NetworkError("connection refused")),
        ])
        with pytest.raises(httpx.NetworkError):
            await _resolve_cik("NVDA", client)


# ---------------------------------------------------------------------------
# _search_efts
# ---------------------------------------------------------------------------


class TestSearchEfts:
    async def test_returns_hits(self):
        client = MockAsyncClient([
            (EFTS_SEARCH_URL, MockResponse(json_data=_EFTS_RESPONSE)),
        ])
        hits = await _search_efts("NVDA", client, fetch_size=10)
        assert len(hits) == 2
        assert hits[0]["_source"]["accession_no"] == "0001045810-24-000123"

    async def test_returns_empty_list_when_no_hits(self):
        empty = {"hits": {"total": {"value": 0}, "hits": []}}
        client = MockAsyncClient([
            (EFTS_SEARCH_URL, MockResponse(json_data=empty)),
        ])
        hits = await _search_efts("FAKE", client, fetch_size=10)
        assert hits == []

    async def test_raises_on_http_error(self):
        client = MockAsyncClient([
            (EFTS_SEARCH_URL, MockResponse(status_code=500)),
        ])
        with pytest.raises(httpx.HTTPStatusError):
            await _search_efts("NVDA", client, fetch_size=10)

    async def test_passes_ticker_as_entity_param(self):
        client = MockAsyncClient([
            (EFTS_SEARCH_URL, MockResponse(json_data=_EFTS_RESPONSE)),
        ])
        await _search_efts("NVDA", client, fetch_size=5)
        _, kwargs = client.calls[0]
        assert kwargs["params"]["entity"] == "NVDA"
        assert kwargs["params"]["forms"] == "8-K"


# ---------------------------------------------------------------------------
# _get_document_url
# ---------------------------------------------------------------------------

_CIK = "0001045810"
_ACC = "0001045810-24-000123"
_ACC_NODASH = "000104581024000123"


class TestGetDocumentUrl:
    def _make_index_url(self):
        return f"{EDGAR_ARCHIVES}/1045810/{_ACC_NODASH}/{_ACC}-index.json"

    async def test_prefers_ex99_exhibit(self):
        client = MockAsyncClient([
            (self._make_index_url(), MockResponse(json_data=_FILING_INDEX_WITH_EXHIBIT)),
        ])
        url = await _get_document_url(_CIK, _ACC, client)
        assert url is not None
        assert "ex991.htm" in url

    async def test_falls_back_to_primary_doc(self):
        client = MockAsyncClient([
            (self._make_index_url(), MockResponse(json_data=_FILING_INDEX_PRIMARY_ONLY)),
        ])
        url = await _get_document_url(_CIK, _ACC, client)
        assert url is not None
        assert "primary.htm" in url

    async def test_returns_none_for_empty_documents(self):
        client = MockAsyncClient([
            (self._make_index_url(), MockResponse(json_data=_FILING_INDEX_EMPTY)),
        ])
        url = await _get_document_url(_CIK, _ACC, client)
        assert url is None

    async def test_returns_none_on_http_error(self):
        client = MockAsyncClient([
            (self._make_index_url(), MockResponse(status_code=404)),
        ])
        url = await _get_document_url(_CIK, _ACC, client)
        assert url is None

    async def test_url_uses_cik_without_leading_zeros(self):
        client = MockAsyncClient([
            (self._make_index_url(), MockResponse(json_data=_FILING_INDEX_WITH_EXHIBIT)),
        ])
        url = await _get_document_url(_CIK, _ACC, client)
        # Archive paths use the integer CIK (no padding)
        assert "/1045810/" in url

    async def test_returns_none_when_document_has_no_filename(self):
        index = {"documents": [{"filename": "", "type": "EX-99.1", "sequence": "1"}]}
        client = MockAsyncClient([
            (self._make_index_url(), MockResponse(json_data=index)),
        ])
        url = await _get_document_url(_CIK, _ACC, client)
        assert url is None


# ---------------------------------------------------------------------------
# _fetch_document_text
# ---------------------------------------------------------------------------

_DOC_URL = "https://www.sec.gov/Archives/edgar/data/1045810/000104581024000123/ex991.htm"


class TestFetchDocumentText:
    async def test_strips_html_from_htm_document(self):
        client = MockAsyncClient([
            (_DOC_URL, MockResponse(text=_TRANSCRIPT_HTML, content_type="text/html")),
        ])
        text = await _fetch_document_text(_DOC_URL, client)
        assert text is not None
        assert "<" not in text
        assert "wordtoken" in text

    async def test_handles_plain_text_document(self):
        client = MockAsyncClient([
            (_DOC_URL, MockResponse(text=_TRANSCRIPT_WORDS, content_type="text/plain")),
        ])
        text = await _fetch_document_text(_DOC_URL, client)
        assert text is not None
        assert "wordtoken" in text

    async def test_strips_sgml_headers_from_txt_files(self):
        sgml_prefix = "SEC EDGAR SUBMISSION\nFORM TYPE: 8-K\n"
        txt_url = _DOC_URL.replace(".htm", ".txt")
        doc_content = sgml_prefix + f"<DOCUMENT>\n<p>{_TRANSCRIPT_WORDS}</p>"
        client = MockAsyncClient([
            (txt_url, MockResponse(text=doc_content, content_type="text/plain")),
        ])
        text = await _fetch_document_text(txt_url, client)
        assert text is not None
        assert "SUBMISSION" not in text

    async def test_returns_none_when_document_too_short(self):
        short_html = "<html><body><p>Too short.</p></body></html>"
        client = MockAsyncClient([
            (_DOC_URL, MockResponse(text=short_html, content_type="text/html")),
        ])
        text = await _fetch_document_text(_DOC_URL, client)
        assert text is None

    async def test_returns_none_on_http_error(self):
        client = MockAsyncClient([
            (_DOC_URL, httpx.NetworkError("timeout")),
        ])
        text = await _fetch_document_text(_DOC_URL, client)
        assert text is None


# ---------------------------------------------------------------------------
# fetch_transcripts  (integration — patches httpx.AsyncClient)
# ---------------------------------------------------------------------------


def _build_client_cm(routes: list[tuple]):
    """Return a mock context manager whose __aenter__ yields a MockAsyncClient."""
    client = MockAsyncClient(routes)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm, client


_INDEX_URL_FRAGMENT = f"{_ACC_NODASH}/{_ACC}-index.json"
_DOC_URL_FRAGMENT = "ex991.htm"


class TestFetchTranscripts:
    async def test_returns_sorted_transcripts(self):
        cm, _ = _build_client_cm([
            (COMPANY_TICKERS_URL, MockResponse(json_data=_COMPANY_TICKERS)),
            (EFTS_SEARCH_URL, MockResponse(json_data=_EFTS_RESPONSE)),
            (_INDEX_URL_FRAGMENT, MockResponse(json_data=_FILING_INDEX_WITH_EXHIBIT)),
            (_DOC_URL_FRAGMENT, MockResponse(text=_TRANSCRIPT_HTML, content_type="text/html")),
        ])
        with patch("backend.data.edgar.httpx.AsyncClient", return_value=cm):
            results = await fetch_transcripts("NVDA", limit=10)

        assert len(results) >= 1
        assert all(isinstance(r, TranscriptResult) for r in results)
        # Must be sorted newest-first
        dates = [r.filing_date for r in results]
        assert dates == sorted(dates, reverse=True)

    async def test_result_fields_are_populated(self):
        cm, _ = _build_client_cm([
            (COMPANY_TICKERS_URL, MockResponse(json_data=_COMPANY_TICKERS)),
            (EFTS_SEARCH_URL, MockResponse(json_data=_EFTS_RESPONSE)),
            (_INDEX_URL_FRAGMENT, MockResponse(json_data=_FILING_INDEX_WITH_EXHIBIT)),
            (_DOC_URL_FRAGMENT, MockResponse(text=_TRANSCRIPT_HTML, content_type="text/html")),
        ])
        with patch("backend.data.edgar.httpx.AsyncClient", return_value=cm):
            results = await fetch_transcripts("NVDA", limit=1)

        r = results[0]
        assert r.ticker == "NVDA"
        assert r.company_name == "NVIDIA Corp"
        assert r.accession_number == "0001045810-24-000123"
        assert r.word_count > 0
        assert r.transcript_text != ""
        assert r.fiscal_quarter is not None

    async def test_raises_for_unknown_ticker(self):
        cm, _ = _build_client_cm([
            (COMPANY_TICKERS_URL, MockResponse(json_data=_COMPANY_TICKERS)),
        ])
        with patch("backend.data.edgar.httpx.AsyncClient", return_value=cm):
            with pytest.raises(ValueError, match="ZZZZ"):
                await fetch_transcripts("ZZZZ")

    async def test_returns_empty_list_when_no_efts_hits(self):
        empty_efts = {"hits": {"total": {"value": 0}, "hits": []}}
        cm, _ = _build_client_cm([
            (COMPANY_TICKERS_URL, MockResponse(json_data=_COMPANY_TICKERS)),
            (EFTS_SEARCH_URL, MockResponse(json_data=empty_efts)),
        ])
        with patch("backend.data.edgar.httpx.AsyncClient", return_value=cm):
            results = await fetch_transcripts("NVDA")
        assert results == []

    async def test_skips_hits_with_unusable_documents(self):
        """Hits whose documents are too short should be silently skipped."""
        short_html = "<html><body><p>Too short to be a transcript.</p></body></html>"
        cm, _ = _build_client_cm([
            (COMPANY_TICKERS_URL, MockResponse(json_data=_COMPANY_TICKERS)),
            (EFTS_SEARCH_URL, MockResponse(json_data=_EFTS_RESPONSE)),
            (_INDEX_URL_FRAGMENT, MockResponse(json_data=_FILING_INDEX_WITH_EXHIBIT)),
            (_DOC_URL_FRAGMENT, MockResponse(text=short_html, content_type="text/html")),
        ])
        with patch("backend.data.edgar.httpx.AsyncClient", return_value=cm):
            results = await fetch_transcripts("NVDA")
        assert results == []

    async def test_respects_limit(self):
        """fetch_transcripts should return at most `limit` results."""
        # Give the mock enough routes: the second hit reuses the same fragments
        cm, _ = _build_client_cm([
            (COMPANY_TICKERS_URL, MockResponse(json_data=_COMPANY_TICKERS)),
            (EFTS_SEARCH_URL, MockResponse(json_data=_EFTS_RESPONSE)),
            (_INDEX_URL_FRAGMENT, MockResponse(json_data=_FILING_INDEX_WITH_EXHIBIT)),
            (_DOC_URL_FRAGMENT, MockResponse(text=_TRANSCRIPT_HTML, content_type="text/html")),
        ])
        with patch("backend.data.edgar.httpx.AsyncClient", return_value=cm):
            results = await fetch_transcripts("NVDA", limit=1)
        assert len(results) <= 1


# ---------------------------------------------------------------------------
# _retrying_get  — retry and backoff behaviour
# ---------------------------------------------------------------------------


class TestRetryingGet:
    """Tests for the _retrying_get helper in isolation."""

    async def test_returns_immediately_on_200(self, _no_sleep):
        url = "https://example.com/api"
        client = MockAsyncClient([(url, MockResponse(json_data={"ok": True}))])
        resp = await _retrying_get(client, url)
        assert resp.json() == {"ok": True}
        # No backoff sleep — only the normal rate-limit sleep is present
        backoff_calls = [c.args[0] for c in _no_sleep.call_args_list if c.args[0] >= _BASE_RETRY_DELAY]
        assert backoff_calls == []

    async def test_retries_on_429_and_succeeds(self, _no_sleep):
        url = "https://example.com/api"
        client = MockAsyncClient([
            (url, [
                MockResponse(status_code=429),   # attempt 1 — rate limited
                MockResponse(json_data={"ok": True}),  # attempt 2 — success
            ]),
        ])
        resp = await _retrying_get(client, url)
        assert resp.json() == {"ok": True}
        assert len(client.calls) == 2

    async def test_retries_on_503_and_succeeds(self, _no_sleep):
        url = "https://example.com/api"
        client = MockAsyncClient([
            (url, [
                MockResponse(status_code=503),
                MockResponse(status_code=503),
                MockResponse(json_data={"ok": True}),
            ]),
        ])
        resp = await _retrying_get(client, url)
        assert resp.json() == {"ok": True}
        assert len(client.calls) == 3

    async def test_backoff_delay_doubles_each_attempt(self, _no_sleep):
        url = "https://example.com/api"
        client = MockAsyncClient([
            (url, [
                MockResponse(status_code=429),
                MockResponse(status_code=429),
                MockResponse(json_data={"ok": True}),
            ]),
        ])
        await _retrying_get(client, url, base_delay=1.0)

        # Filter out the _REQUEST_DELAY calls (0.11 s) — keep only backoff delays
        all_delays = [c.args[0] for c in _no_sleep.call_args_list]
        backoff_delays = [d for d in all_delays if d >= 1.0]
        assert backoff_delays == [1.0, 2.0]   # base * 2^0, base * 2^1

    async def test_raises_after_exhausting_retries(self, _no_sleep):
        url = "https://example.com/api"
        # Always 429 — more responses than retries to confirm limit is enforced
        client = MockAsyncClient([
            (url, [MockResponse(status_code=429)] * (_MAX_RETRIES + 2)),
        ])
        with pytest.raises(httpx.HTTPStatusError):
            await _retrying_get(client, url)
        assert len(client.calls) == _MAX_RETRIES + 1

    async def test_does_not_retry_on_404(self, _no_sleep):
        """Non-retryable 4xx errors must raise immediately without retrying."""
        url = "https://example.com/api"
        client = MockAsyncClient([(url, MockResponse(status_code=404))])
        with pytest.raises(httpx.HTTPStatusError):
            await _retrying_get(client, url)
        assert len(client.calls) == 1
        backoff_calls = [c.args[0] for c in _no_sleep.call_args_list if c.args[0] >= _BASE_RETRY_DELAY]
        assert backoff_calls == []

    async def test_search_efts_retries_on_429(self, _no_sleep):
        """End-to-end: _search_efts recovers after a 429 from EFTS."""
        client = MockAsyncClient([
            (EFTS_SEARCH_URL, [
                MockResponse(status_code=429),
                MockResponse(json_data=_EFTS_RESPONSE),
            ]),
        ])
        hits = await _search_efts("NVDA", client, fetch_size=10)
        assert len(hits) == 2
        efts_calls = [url for url, _ in client.calls if EFTS_SEARCH_URL in url]
        assert len(efts_calls) == 2

    async def test_fetch_document_text_retries_on_503(self, _no_sleep):
        """End-to-end: _fetch_document_text recovers after a 503."""
        client = MockAsyncClient([
            (_DOC_URL, [
                MockResponse(status_code=503),
                MockResponse(text=_TRANSCRIPT_HTML, content_type="text/html"),
            ]),
        ])
        text = await _fetch_document_text(_DOC_URL, client)
        assert text is not None
        assert "wordtoken" in text
        assert len(client.calls) == 2
