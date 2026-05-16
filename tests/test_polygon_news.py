"""Tests for the news surface: normaliser, provider method, and tool wrapper.

No live HTTP — the Polygon client is monkeypatched via the same
`voli.providers.polygon.PolygonClient` seam the option tests already use.
"""

from __future__ import annotations

from datetime import UTC

import voli.tools.polygon_tools as pt
from voli.polygon.normalise import news_item_from_polygon_row
from voli.tool_schemas import GetTickerNewsInput

# --- fixtures (raw Polygon-ish rows) ---

NEWS_ROW_1 = {
    "id": "abc123",
    "publisher": {"name": "Reuters", "homepage_url": "https://reuters.com"},
    "title": "Intel announces foundry milestone",
    "author": "Jane Doe",
    "published_utc": "2026-05-15T13:30:00Z",
    "article_url": "https://example.com/news/intel-foundry",
    "tickers": ["INTC", "TSMC"],
    "description": "Intel said its 18A node is on schedule.",
}

NEWS_ROW_2 = {
    "id": "def456",
    "publisher": {"name": "Bloomberg"},
    "title": "Chip stocks rise on AI demand",
    "published_utc": "2026-05-15T09:00:00Z",
    "article_url": "https://example.com/news/chip-rally",
    "tickers": ["INTC", "NVDA", "AMD"],
}

NEWS_ROW_MISSING_PUBLISHER = {
    "id": "ghi789",
    # publisher key entirely missing
    "title": "Mystery analyst piece",
    "published_utc": "2026-05-14T20:15:00Z",
    "article_url": "https://example.com/news/mystery",
    "tickers": ["INTC"],
}


# --- normaliser ---


def test_normaliser_maps_all_fields():
    item = news_item_from_polygon_row(NEWS_ROW_1)
    assert item.id == "abc123"
    assert item.title == "Intel announces foundry milestone"
    assert item.publisher == "Reuters"
    assert item.tickers == ["INTC", "TSMC"]
    assert item.article_url == "https://example.com/news/intel-foundry"
    assert item.description == "Intel said its 18A node is on schedule."
    assert item.author == "Jane Doe"
    assert item.source == "polygon"
    # Timestamp parsed as UTC-aware.
    assert item.published_utc.tzinfo is not None
    assert item.published_utc.astimezone(UTC).tzinfo == UTC


def test_normaliser_handles_missing_publisher():
    item = news_item_from_polygon_row(NEWS_ROW_MISSING_PUBLISHER)
    assert item.publisher == "unknown"
    assert item.description is None
    assert item.author is None


# --- Fake client ---


class FakeNewsClient:
    def __init__(self, *args, **kwargs):
        self.calls: list[tuple[str, int]] = []

    def close(self) -> None:
        pass

    def list_ticker_news(self, ticker: str, *, limit: int = 10, order: str = "desc"):
        self.calls.append((ticker, limit))
        return {"results": [NEWS_ROW_1, NEWS_ROW_2]}


_LAST_CLIENT: FakeNewsClient | None = None


def _install_fake_client(monkeypatch):
    """Patch the Polygon client constructor at the provider's import site."""

    def _ctor(*args, **kwargs):
        global _LAST_CLIENT
        _LAST_CLIENT = FakeNewsClient()
        return _LAST_CLIENT

    monkeypatch.setattr("voli.providers.polygon.PolygonClient", _ctor)


# --- provider + wrapper ---


def test_get_ticker_news_returns_items_with_meta(monkeypatch):
    _install_fake_client(monkeypatch)

    out = pt.get_ticker_news(GetTickerNewsInput(ticker="INTC", limit=5))

    assert out.meta.tool == "get_ticker_news"
    assert out.meta.primary_source == "polygon"
    assert len(out.news) == 2
    assert out.news[0].id == "abc123"
    assert out.news[0].publisher == "Reuters"
    assert _LAST_CLIENT is not None
    assert _LAST_CLIENT.calls == [("INTC", 5)]


def test_get_ticker_news_cache_hit_on_repeat(monkeypatch, tmp_path):
    """First call hits the provider; the second hits the SQLite cache and
    leaves the vendor untouched. Uses an isolated tmp_path cache so cross-test
    state doesn't pollute the result."""

    cache_path = tmp_path / "cache.sqlite"
    monkeypatch.setenv("VOLI_CACHE_PATH", str(cache_path))
    pt._get_cache.cache_clear()
    _install_fake_client(monkeypatch)

    first = pt.get_ticker_news(GetTickerNewsInput(ticker="INTC", limit=5))
    assert first.meta.primary_source == "polygon"
    calls_after_first = len(_LAST_CLIENT.calls)

    second = pt.get_ticker_news(GetTickerNewsInput(ticker="INTC", limit=5))
    assert second.meta.primary_source == "cache"
    # No additional vendor call on the cache-hit path.
    assert len(_LAST_CLIENT.calls) == calls_after_first

    pt._get_cache().close()
    pt._get_cache.cache_clear()


def test_get_ticker_news_no_results_emits_warning(monkeypatch):
    class EmptyClient(FakeNewsClient):
        def list_ticker_news(self, ticker: str, *, limit: int = 10, order: str = "desc"):
            return {"results": []}

    def _ctor(*args, **kwargs):
        global _LAST_CLIENT
        _LAST_CLIENT = EmptyClient()
        return _LAST_CLIENT

    monkeypatch.setattr("voli.providers.polygon.PolygonClient", _ctor)

    out = pt.get_ticker_news(GetTickerNewsInput(ticker="ZZZZ"))
    assert out.news == []
    assert "NO_RESULTS" in out.meta.warnings


def test_get_ticker_news_provider_without_news_returns_vendor_limit(monkeypatch):
    """A custom provider that doesn't implement fetch_news should be handled
    gracefully — the wrapper catches NotImplementedError and emits
    VENDOR_LIMIT with an empty list."""

    class NoNewsProvider:
        name = "stub"

        def fetch_news(self, ticker, *, limit=10):
            raise NotImplementedError

    monkeypatch.setattr(pt, "get_active", lambda: NoNewsProvider())

    out = pt.get_ticker_news(GetTickerNewsInput(ticker="INTC", limit=3))
    assert out.news == []
    assert "VENDOR_LIMIT" in out.meta.warnings
    assert out.meta.primary_source == "stub"
