# Capacity Plan

Based on measured load test results from Bronze, Silver, and Gold tiers. All tests ran on a single developer MacBook (Apple Silicon) with Docker Desktop, which adds ~10–50ms virtualization overhead per request. Numbers should be interpreted as relative comparisons, not absolute production benchmarks.

---

## Measured Capacity — Current Stack

### Test environment

| Component | Spec |
|---|---|
| Host | macOS (Apple Silicon) + Docker Desktop |
| Flask replicas | 3 × gunicorn, 4 sync workers each |
| Gunicorn total capacity | 12 concurrent request handlers |
| PostgreSQL | postgres:16-alpine (single node, no read replica) |
| Redis | redis:7-alpine (single node) |
| Load generator | k6 on the same host |

### Results summary

| Tier | Concurrent users | Duration | RPS | p95 latency | Error rate | Cache hit rate |
|---|---|---|---|---|---|---|
| **Bronze** | 50 | 30s | 47 | 1011 ms | 0% | N/A (no cache) |
| **Silver** | 200 | 60s | 163 | 1935 ms | 0% | N/A (no cache) |
| **Gold** | 500 | 120s | 122 | 7643 ms | 0% | 98.25% |

> Gold latency is higher than Silver despite caching because 500 VUs overwhelm the 12-worker pool. The DB is no longer the bottleneck (98% cache hit rate), but the worker queue is.

---

## Where the Limits Are

### Limit 1 — Gunicorn worker pool (current bottleneck)

**Observed:** At 200 VUs (Silver), the 12 sync workers serve ~163 RPS with 1.9s p95. At 500 VUs (Gold), the queue backs up and p95 climbs to 7.6s.

**Calculation:**
```
Theoretical max RPS = workers × (1000ms / service_time_ms)
                    = 12 × (1000 / 15ms per cache HIT on macOS Docker)
                    = ~800 RPS (theoretical ceiling)

Actual observed max ≈ 163 RPS (constrained by Docker VM overhead)
```

**Break-even:** The worker pool saturates somewhere between 200–300 VUs on this hardware.

### Limit 2 — PostgreSQL (cache miss path)

At 98% cache hit rate, the DB receives ~2% of traffic:
```
163 RPS × 0.02 = ~3 DB queries/second
```

PostgreSQL's default `max_connections=100` means the DB can handle the current load comfortably. The DB would become a bottleneck if:
- Cache hit rate drops below ~50%, or
- RPS grows past ~500 (50% miss × 500 RPS = 250 DB QPS, which is still manageable but approaches the connection limit with 12 workers).

### Limit 3 — Redis (single node)

Redis is single-threaded but extremely fast. At the measured ~3000 requests/second theoretical ceiling, Redis would be well below saturation. Redis becomes a bottleneck only with very large values (the `products:all` list grows with the product count) or when all 12 workers hammer the same key simultaneously (thundering herd on cache expiry — not currently mitigated).

---

## Scaling Ladder

What to do next, in order of impact vs. effort:

### Step 1 — Switch to `gevent` workers (free, low effort)

```bash
# docker-entrypoint.sh
uv add gevent
exec uv run gunicorn \
  --worker-class gevent \
  --workers 4 \
  --worker-connections 200 \
  "app:create_app()"
```

**Expected impact:** 4 workers × 200 connections = 800 concurrent handlers per instance (vs. 4 today). At 98% cache hit rate, each handler spends <5ms in I/O. Estimated throughput: **500–800 RPS** on current hardware.

### Step 2 — Add PgBouncer (low effort, required before gevent)

`gevent` workers share OS threads, which can open many DB connections. PgBouncer pools them:

```yaml
# docker-compose.yml
pgbouncer:
  image: pgbouncer/pgbouncer
  environment:
    DB_HOST: db
    DB_PORT: 5432
    DB_NAME: hackathon_db
    DB_USER: postgres
    DB_PASSWORD: postgres
    POOL_MODE: transaction
    MAX_CLIENT_CONN: 200
    DEFAULT_POOL_SIZE: 20
```

**Expected impact:** Caps PostgreSQL at 20 actual connections regardless of how many workers/threads exist.

### Step 3 — Add a 4th app replica (medium effort)

Add `app4` to `docker-compose.yml` and `server app4:5000;` to `nginx.conf`.

**Expected impact at current worker class:** ~33% more worker capacity (16 → 20 workers, or with gevent: 1000 → 1200 concurrent handlers).

### Step 4 — Add a PostgreSQL read replica (high effort)

For workloads where cache miss rate is high or data freshness requirements prevent long TTLs, route all `SELECT` queries to a read replica.

**Expected impact:** Doubles read throughput from PostgreSQL; primary is used only for writes.

### Step 5 — Deploy on Linux (changes everything)

All latency measurements in this plan are inflated by Docker Desktop's macOS hypervisor (~10–50ms per container hop). On a Linux host:
- Container networking overhead: ~0.1ms (vs. 10–50ms on macOS Docker)
- Cache HITs: ~1ms end-to-end (vs. ~12ms on macOS Docker)
- Expected RPS at 500 VUs: **2000–5000 RPS** (same code, same architecture)

---

## Cost Projections

### Cloud deployment (AWS, single region)

| Component | Service | Size | Monthly cost (est.) |
|---|---|---|---|
| App replicas (3×) | ECS Fargate, 0.5 vCPU / 1GB | 3 tasks | ~$30 |
| PostgreSQL | RDS PostgreSQL 16 db.t3.micro | 1 instance | ~$25 |
| Redis | ElastiCache Redis t3.micro | 1 node | ~$20 |
| Load balancer | ALB | 1 ALB | ~$20 |
| **Total** | | | **~$95/month** |

### Scaling cost to 10× traffic

| Change | Additional cost |
|---|---|
| App replicas: 3 → 9 | +$60 (6 more Fargate tasks) |
| DB: t3.micro → t3.small | +$25 |
| Redis: t3.micro → t3.small | +$20 |
| **Total at 10× traffic** | **~$200/month** |

### When to scale

| Trigger | Action |
|---|---|
| p95 > 1s sustained for > 5 min | Add app replicas |
| DB CPU > 70% sustained | Add read replica or upgrade instance |
| Redis memory > 80% of limit | Increase `maxmemory` or upgrade instance |
| Error rate > 1% | Investigate before scaling (scaling rarely fixes bugs) |

---

## Capacity Summary Card

```
Current stack (Docker on macOS developer laptop):
  Concurrent users supported: ~200 (Silver, p95 < 2s)
  Peak throughput: ~163 req/s
  Database queries eliminated by cache: 98%
  Hard limit: 12 gunicorn sync workers

Next unlock (gevent workers, same hardware):
  Estimated concurrent users: ~500–1000
  Estimated peak throughput: ~500 RPS

Production ceiling (Linux, gevent, PgBouncer, 3 replicas):
  Estimated concurrent users: 2000+
  Estimated peak throughput: 2000–5000 RPS
  Database handles: ~40–100 actual connections via PgBouncer
```
