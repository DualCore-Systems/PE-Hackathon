"""Tests for the Redis cache module."""
from unittest.mock import MagicMock, patch

from app.cache import (
    CACHE_TTL,
    HIT_COUNTER,
    MISS_COUNTER,
    cache_delete,
    cache_get,
    cache_set,
    cache_stats,
)


class TestCacheGet:
    @patch("app.cache._client_or_raise")
    def test_cache_hit(self, mock_client_fn):
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client
        mock_client.get.return_value = '{"id": 1, "name": "Widget"}'

        result = cache_get("products:1")

        assert result == {"id": 1, "name": "Widget"}
        mock_client.incr.assert_called_once_with(HIT_COUNTER)

    @patch("app.cache._client_or_raise")
    def test_cache_miss(self, mock_client_fn):
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client
        mock_client.get.return_value = None

        result = cache_get("products:999")

        assert result is None
        mock_client.incr.assert_called_once_with(MISS_COUNTER)

    @patch("app.cache._client_or_raise", side_effect=RuntimeError("not init"))
    def test_cache_get_returns_none_on_error(self, mock_client_fn):
        result = cache_get("anything")
        assert result is None


class TestCacheSet:
    @patch("app.cache._client_or_raise")
    def test_cache_set_stores_value(self, mock_client_fn):
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client

        cache_set("products:all", [{"id": 1}])

        mock_client.setex.assert_called_once()
        args = mock_client.setex.call_args[0]
        assert args[0] == "products:all"
        assert args[1] == CACHE_TTL

    @patch("app.cache._client_or_raise")
    def test_cache_set_custom_ttl(self, mock_client_fn):
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client

        cache_set("key", {"data": True}, ttl=300)

        args = mock_client.setex.call_args[0]
        assert args[1] == 300

    @patch("app.cache._client_or_raise", side_effect=RuntimeError("not init"))
    def test_cache_set_ignores_error(self, mock_client_fn):
        cache_set("key", {"data": True})  # should not raise


class TestCacheDelete:
    @patch("app.cache._client_or_raise")
    def test_cache_delete_removes_keys(self, mock_client_fn):
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client

        cache_delete("products:all", "products:1")

        mock_client.delete.assert_called_once_with("products:all", "products:1")

    @patch("app.cache._client_or_raise", side_effect=RuntimeError("not init"))
    def test_cache_delete_ignores_error(self, mock_client_fn):
        cache_delete("key")  # should not raise


class TestCacheStats:
    @patch("app.cache._client_or_raise")
    def test_cache_stats_with_data(self, mock_client_fn):
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client
        mock_client.get.side_effect = lambda k: "100" if k == HIT_COUNTER else "10"

        stats = cache_stats()

        assert stats["hits"] == 100
        assert stats["misses"] == 10
        assert stats["total_requests"] == 110
        assert "90.9%" in stats["hit_rate"]

    @patch("app.cache._client_or_raise")
    def test_cache_stats_empty(self, mock_client_fn):
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client
        mock_client.get.return_value = None

        stats = cache_stats()

        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["hit_rate"] == "N/A"

    @patch("app.cache._client_or_raise", side_effect=RuntimeError("down"))
    def test_cache_stats_unavailable(self, mock_client_fn):
        stats = cache_stats()
        assert "error" in stats
        assert "unavailable" in stats["error"]
