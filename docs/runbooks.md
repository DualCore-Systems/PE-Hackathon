# Runbooks

Step-by-step operational guides for the most common incidents. Each runbook follows the same structure: **Detect → Confirm → Fix → Verify → Post-mortem note**.

---

## Runbook 1 — App is Slow

**Definition:** p95 response time exceeds 2× the normal baseline, or users report timeouts.

### 1. Detect

```bash
# Quick latency spot-check via curl
time curl -s http://127.0.0.1:80/products/1 > /dev/null
# Normal: < 50ms on cache HIT. Slow: > 500ms.

# Check cache hit rate — if this drops, DB is under pressure
curl -s http://127.0.0.1:80/cache/stats
# Healthy: hit_rate > 90%. Degraded: hit_rate < 50%.
```

### 2. Confirm

```bash
# Check all containers are running
docker compose ps

# Check resource usage
docker stats --no-stream

# Inspect recent app logs for slow queries or errors
docker compose logs --tail=100 app1 | grep -E "ERROR|WARNING|[0-9]{4,}ms"
```

### 3. Diagnose

**Is Redis down?** → See [Runbook 3 — Redis is Down](#runbook-3--redis-is-down).

**Is the cache hit rate low?**
```bash
# Flush old keys and let the cache warm up naturally
docker exec pe-hackathon-redis-1 redis-cli FLUSHDB
# Cache will rebuild on first request to each endpoint
```

**Are workers saturated?**
```bash
# Check how many gunicorn workers are active vs idle
docker compose exec app1 ps aux | grep gunicorn | wc -l
# Should be (--workers + 1) master + N workers = 5 for --workers 4

# If all workers show 100% CPU, the pool is saturated
# Increase workers in docker-entrypoint.sh and rebuild
```

**Is the database slow?**
```bash
# Connect to Postgres and check for long-running queries
docker exec -it pe-hackathon-db-1 psql -U postgres -d hackathon_db -c "
SELECT pid, now() - pg_stat_activity.query_start AS duration, query, state
FROM pg_stat_activity
WHERE state != 'idle' AND query_start < now() - interval '1 second'
ORDER BY duration DESC;
"
```

### 4. Fix

| Root cause | Fix |
|---|---|
| Redis down | See Runbook 3 |
| Cache cold (after restart) | Wait ~60s for TTL-based warming, or run a warm-up script |
| Worker pool saturated | Increase `--workers` in `docker-entrypoint.sh`, rebuild |
| DB slow query | Add index, optimize query, or reduce page size |
| Single replica stuck | `docker compose restart app2` (Nginx routes away automatically) |

### 5. Verify

```bash
time curl -s http://127.0.0.1:80/products/1 > /dev/null
curl -s http://127.0.0.1:80/cache/stats
```

---

## Runbook 2 — High Error Rate

**Definition:** HTTP 5xx responses exceed 1% of traffic, or k6 shows `http_req_failed > 0.01`.

### 1. Detect

```bash
# Check for recent errors in Nginx log
docker compose logs nginx --tail=200 | grep -E '" 5[0-9]{2} '

# Check app logs for Python exceptions
docker compose logs app1 --tail=200 | grep -E "ERROR|Traceback|Exception"
```

### 2. Confirm

```bash
# Hit each endpoint manually
curl -i http://127.0.0.1:80/health
curl -i http://127.0.0.1:80/products
curl -i http://127.0.0.1:80/products/1
```

### 3. Diagnose

**502 from Nginx** → app containers are down or not accepting connections. See [Troubleshooting — Nginx 502](troubleshooting.md#nginx-returns-502-bad-gateway).

**500 from Flask** → Python exception inside a route handler. Check app logs:

```bash
docker compose logs app1 --tail=50 | grep -A10 "ERROR"
```

**Database errors** (e.g., `OperationalError: too many connections`):
```bash
docker exec -it pe-hackathon-db-1 psql -U postgres -c "SELECT count(*) FROM pg_stat_activity;"
# If count is high, gunicorn is opening too many connections
# Fix: reduce --workers, add PgBouncer, or increase max_connections in postgres
```

### 4. Fix

| Error type | Fix |
|---|---|
| 502 Bad Gateway | Restart app containers: `docker compose restart app1 app2 app3` |
| 500 Python exception | Fix the bug, rebuild, rolling restart |
| DB `too many connections` | Reduce worker count or add PgBouncer |
| Disk full on DB host | `docker system prune` to reclaim Docker overlay storage |

### 5. Verify

```bash
# Run a quick load test to confirm error rate is 0%
k6 run --vus 10 --duration 30s loadtest/bronze_test.js
```

---

## Runbook 3 — Redis is Down

**Definition:** `GET /cache/stats` returns `{"error": "cache unavailable: …"}`, or all requests show `X-Cache: MISS`.

### Impact

- **User-facing:** No immediate degradation — the app falls back to direct DB reads.
- **Performance:** Cache miss rate spikes to 100%; DB load increases proportionally. Under heavy traffic, this can cascade into DB saturation.
- **Cache stats:** Hit/miss counters stop incrementing.

### 1. Detect

```bash
curl -s http://127.0.0.1:80/cache/stats
# {"error": "cache unavailable: Connection refused"}

# Also check X-Cache header on all requests
curl -si http://127.0.0.1:80/products/1 | grep X-Cache
# X-Cache: MISS  (even on repeated requests = Redis is down)
```

### 2. Confirm

```bash
docker compose ps redis
# Is it "Up (healthy)"? If not:
docker compose logs redis --tail=50
```

### 3. Fix

**Redis crashed or OOM-killed:**
```bash
docker compose up -d redis
# Wait for healthcheck to pass (~5s), then verify:
docker compose ps redis
# Should show "Up (healthy)"
```

**Redis data corrupted:**
```bash
docker compose stop redis
docker compose rm -f redis
docker compose up -d redis
# Cache will rebuild organically as requests come in
```

**Redis out of memory (if maxmemory is set):**
```bash
docker exec pe-hackathon-redis-1 redis-cli INFO memory | grep used_memory_human
# If near maxmemory, either increase it or flush:
docker exec pe-hackathon-redis-1 redis-cli FLUSHDB
```

### 4. Verify

```bash
# Cache should reconnect automatically (connection pool retries on next request)
curl -si http://127.0.0.1:80/products/1 | grep X-Cache
# First request: X-Cache: MISS (Redis is empty, querying DB)
curl -si http://127.0.0.1:80/products/1 | grep X-Cache
# Second request: X-Cache: HIT (cache rebuilt)

curl -s http://127.0.0.1:80/cache/stats
# Should show hits/misses again
```

### Post-mortem note

Redis downtime does not require a cache warm-up script. The cache-aside pattern naturally repopulates keys as they are requested. Under normal traffic, the cache is fully warm within one TTL period (60 seconds).

---

## Runbook 4 — Database is Full / Storage Issues

**Definition:** Postgres logs `no space left on device`, or the `pgdata` Docker volume is growing unexpectedly.

### 1. Detect

```bash
# Check volume usage
docker system df -v | grep pgdata

# Check postgres for bloat
docker exec -it pe-hackathon-db-1 psql -U postgres -d hackathon_db -c "
SELECT
  relname AS table_name,
  pg_size_pretty(pg_total_relation_size(relid)) AS total_size
FROM pg_catalog.pg_stattab
ORDER BY pg_total_relation_size(relid) DESC
LIMIT 10;
"

# Simpler: check table sizes
docker exec -it pe-hackathon-db-1 psql -U postgres -d hackathon_db -c "
SELECT tablename, pg_size_pretty(pg_total_relation_size(tablename::regclass))
FROM pg_tables WHERE schemaname = 'public' ORDER BY 2 DESC;
"
```

### 2. Confirm

```bash
# Try a simple insert — will fail immediately if disk is full
docker compose exec app1 uv run python -c "
from app import create_app
app = create_app()
with app.app_context():
    from app.models.product import Product
    print(Product.select().count())
"
```

### 3. Fix

**Reclaim Docker storage (logs, dangling images, stopped containers):**
```bash
docker system prune -f
# Does NOT touch named volumes (pgdata is safe)
```

**Vacuum PostgreSQL (reclaim dead tuple space):**
```bash
docker exec -it pe-hackathon-db-1 psql -U postgres -d hackathon_db -c "VACUUM FULL ANALYZE;"
```

**Delete old/test data:**
```bash
# Example: delete products with stock=0 (if business logic allows)
docker exec -it pe-hackathon-db-1 psql -U postgres -d hackathon_db -c "
DELETE FROM product WHERE stock = 0;
VACUUM ANALYZE product;
"
```

**Increase Docker volume size:** On Docker Desktop, go to **Settings → Resources → Disk image size** and increase the allocation. Restart Docker Desktop.

### 4. Verify

```bash
docker system df -v | grep pgdata
curl -s http://127.0.0.1:80/products | python3 -c "import sys,json; print(len(json.load(sys.stdin)), 'products')"
```

---

## Quick Reference

| Symptom | First command | Runbook |
|---|---|---|
| Slow responses | `curl -s /cache/stats` | [#1](#runbook-1--app-is-slow) |
| 5xx errors | `docker compose logs nginx --tail=50` | [#2](#runbook-2--high-error-rate) |
| X-Cache always MISS | `docker compose ps redis` | [#3](#runbook-3--redis-is-down) |
| Write operations failing | `docker compose logs db --tail=50` | [#4](#runbook-4--database-is-full--storage-issues) |
