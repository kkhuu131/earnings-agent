"""Shared test fixtures and helpers for the earnings-agent test suite."""

import httpx
import pytest


# ---------------------------------------------------------------------------
# HTTP mocking primitives
# ---------------------------------------------------------------------------


class MockResponse:
    """Minimal stand-in for an httpx.Response.

    Pass json_data for JSON endpoints, text for document-text endpoints.
    Setting status_code >= 400 makes raise_for_status() raise HTTPStatusError.
    """

    def __init__(
        self,
        json_data=None,
        text: str = "",
        status_code: int = 200,
        content_type: str = "application/json",
    ) -> None:
        self._json = json_data
        self.text = text
        self.status_code = status_code
        self.headers = {"content-type": content_type}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("GET", "https://example.com"),
                response=httpx.Response(self.status_code),
            )

    def json(self):
        if self._json is None:
            raise ValueError("MockResponse: no json_data provided")
        return self._json


class MockAsyncClient:
    """Async drop-in for httpx.AsyncClient with URL-based routing.

    ``routes`` is a list of ``(url_fragment, response_or_exception)`` pairs
    checked in order.  The first fragment that appears anywhere in the
    requested URL wins.

    The response value can be:
    - A single MockResponse / Exception — returned on every call to that route.
    - A list of MockResponse / Exception — consumed one per call in sequence;
      the last entry is repeated once the list is exhausted.  This lets you
      simulate 429 → retry → 200 sequences.

    ``calls`` records every (url, kwargs) for assertion in tests.
    """

    def __init__(self, routes: list[tuple]) -> None:
        self.routes = routes
        self._call_counts: dict[int, int] = {}   # route index → call count
        self.calls: list[tuple] = []             # (url, kwargs)

    async def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        for idx, (fragment, response) in enumerate(self.routes):
            if fragment in str(url):
                if isinstance(response, list):
                    count = self._call_counts.get(idx, 0)
                    self._call_counts[idx] = count + 1
                    # Clamp to last entry once exhausted
                    result = response[min(count, len(response) - 1)]
                else:
                    result = response

                if isinstance(result, Exception):
                    raise result
                return result

        raise AssertionError(
            f"MockAsyncClient: no route matched URL '{url}'.\n"
            f"Registered fragments: {[r[0] for r in self.routes]}"
        )
