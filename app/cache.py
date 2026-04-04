"""Redis-backed cache with shared hit/miss counters across all app instances."""
import json
import os

import redis
from redis.connection import ConnectionPool

_pool: ConnectionPool | None = None
_client: redis.Redis | None = None

PRODUCTS_ALL_KEY = "products:all"
PRODUCT_KEY = "products:{id}"
CACHE_TTL = 60  # seconds

HIT_COUNTER = "cache:hits"
MISS_COUNTER = "cache:misses"


def init_cache() -> None:
    global _pool, _client
    _pool = ConnectionPool(
        host=os.environ.get("REDIS_HOST", "localhost"),
        port=int(os.environ.get("REDIS_PORT", 6379)),
        db=0,
        decode_responses=True,
        max_connections=30,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    _client = redis.Redis(connection_pool=_pool)


def _client_or_raise() -> redis.Redis:
    if _client is None:
        raise RuntimeError("Cache not initialised — call init_cache() first")
    return _client


# ── public API ────────────────────────────────────────────────────────────────

def cache_get(key: str) -> dict | list | None:
    """Return cached value and increment hit counter, or None on miss/error."""
    try:
        raw = _client_or_raise().get(key)
        if raw is None:
            _client.incr(MISS_COUNTER)
            return None
        _client.incr(HIT_COUNTER)
        return json.loads(raw)
    except Exception:
        return None


def cache_set(key: str, value: dict | list, ttl: int = CACHE_TTL) -> None:
    """Store value as JSON with an expiry. Silently ignores errors."""
    try:
        _client_or_raise().setex(key, ttl, json.dumps(value, default=str))
    except Exception:
        pass


def cache_delete(*keys: str) -> None:
    """Delete one or more keys. Silently ignores errors."""
    try:
        _client_or_raise().delete(*keys)
    except Exception:
        pass


def cache_stats() -> dict:
    """Return shared hit/miss stats stored in Redis."""
    try:
        c = _client_or_raise()
        hits = int(c.get(HIT_COUNTER) or 0)
        misses = int(c.get(MISS_COUNTER) or 0)
        total = hits + misses
        return {
            "hits": hits,
            "misses": misses,
            "total_requests": total,
            "hit_rate": f"{hits / total * 100:.1f}%" if total > 0 else "N/A",
        }
    except Exception as exc:
        return {"error": f"cache unavailable: {exc}"}
