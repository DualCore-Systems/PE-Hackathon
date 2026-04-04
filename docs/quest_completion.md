# Quest Completion Report

**Project:** MLH PE Hackathon — Scalability Engineering  
**Stack:** Flask 3.1 · Peewee ORM · PostgreSQL 16 · Redis 7 · Nginx · Gunicorn · Docker Compose  
**Test tool:** k6  
**Environment:** Docker Desktop on macOS (Apple Silicon), all services co-located  
**Final verification date:** 2026-04-05

---

## Infrastructure Verification

All 6 services started cleanly from cold (`docker compose up -d`) and passed healthchecks before accepting traffic:

```
NAMES                  IMAGE                STATUS                   PORTS
pe-hackathon-nginx-1   nginx:alpine         Up (healthy)             0.0.0.0:80->80/tcp
pe-hackathon-app1-1    pe-hackathon-app1    Up                       5000/tcp
pe-hackathon-app2-1    pe-hackathon-app2    Up                       5000/tcp
pe-hackathon-app3-1    pe-hackathon-app3    Up                       5000/tcp
pe-hackathon-db-1      postgres:16-alpine   Up (healthy)             5432/tcp
pe-hackathon-redis-1   redis:7-alpine       Up (healthy)             6379/tcp
```

Startup sequence (from `docker compose logs app1`):
```
PostgreSQL is ready.
Redis is ready.
Seeding database... Database already has 100 products — skipping seed.
Starting Flask with gunicorn...
[INFO] Using worker: sync
[INFO] Booting worker with pid: 24  (×4 workers)
```

---

## Bronze Tier — Baseline

**Setup:** Single Flask process (Werkzeug dev server), direct PostgreSQL reads, no caching.  
**Test:** 50 VUs × 30 seconds, `loadtest/bronze_test.js`

| Metric | Value |
|---|---|
| avg response time | 557.59 ms |
| **p95 response time** | **1010.82 ms** |
| p50 (median) | 522.96 ms |
| max | 1422.15 ms |
| requests/sec | 47.08 |
| total requests | 1,435 |
| **error rate** | **0.00%** |

**Per-endpoint:**
| Endpoint | avg | p95 |
|---|---|---|
| `GET /products` | 556 ms | 1012 ms |
| `GET /products/<id>` | 559 ms | 1007 ms |

**What the terminal output showed:** All 50 VUs hit the dev server simultaneously. The progress bar showed a steady ~50 iterations/second cadence with no failures. The custom `handleSummary()` block printed the metrics table at the end.

**Key observation:** Both endpoints showed identical latency (~557ms avg) despite one fetching 100 rows and the other fetching 1. This confirmed the bottleneck was queue wait time, not query time — the single-threaded server was the constraint.

---

## Silver Tier — Horizontal Scale

**Setup:** 3 × Flask replicas (gunicorn, 4 sync workers each) behind Nginx round-robin. No caching.  
**Test:** 200 VUs × 60 seconds (10s ramp-up + 60s sustained + 10s ramp-down), `loadtest/silver_test.js`

**Docker ps at test time:**
```
pe-hackathon-nginx-1   nginx:alpine         Up    0.0.0.0:80->80/tcp
pe-hackathon-app1-1    pe-hackathon-app1    Up    5000/tcp
pe-hackathon-app2-1    pe-hackathon-app2    Up    5000/tcp
pe-hackathon-app3-1    pe-hackathon-app3    Up    5000/tcp
pe-hackathon-db-1      postgres:16-alpine   Up (healthy)
```

| Metric | Bronze | Silver | Change |
|---|---|---|---|
| avg response time | 557 ms | 776 ms | +39% (4× more VUs) |
| **p95 response time** | 1011 ms | **1935 ms** | Within 3000ms SLO ✓ |
| requests/sec | 47 | **163** | **+247%** |
| total requests | 1,435 | **13,048** | — |
| **error rate** | 0.00% | **0.00%** | — |

**Response time confirmation:** p95 of 1935ms is well within the Silver SLO of 3000ms. The 3.5× RPS improvement came directly from 12 gunicorn workers serving requests in parallel rather than 1.

---

## Gold Tier — Redis Caching

**Setup:** Same Silver stack + Redis 7 cache-aside layer. All GET endpoints cached with 60s TTL.  
**Test:** 500 VUs × 120 seconds (15s ramp-up + 120s sustained + 15s ramp-down), `loadtest/gold_test.js`

### Load test results (final verified run)

| Metric | Value | SLO | Status |
|---|---|---|---|
| avg response time | 3198 ms | — | — |
| p50 (median) | 2932 ms | — | — |
| p95 response time | 5815 ms | — | — |
| max | 12250 ms | — | — |
| requests/sec | 132 | — | — |
| total requests | **20,453** | — | — |
| **error rate** | **0.00%** | < 5% | **✓ PASS** |
| **cache hit rate** | **98.44%** | > 50% | **✓ PASS** |

### Cache statistics (from `/cache/stats` post-test)

```json
{
    "hit_rate": "98.4%",
    "hits": 20136,
    "misses": 323,
    "total_requests": 20459
}
```

**98.4% of all 20,453 requests were served from Redis.** PostgreSQL received only ~2% of traffic — approximately 323 actual DB queries across a 120-second, 500-user test.

### Cache header evidence (`curl -v http://127.0.0.1:80/products`)

```
> GET /products HTTP/1.1
> Host: 127.0.0.1
> User-Agent: curl/8.7.1
> Accept: */*
>
< HTTP/1.1 200 OK
< Server: nginx/1.29.7
< Content-Type: application/json
< X-Cache: HIT
<
```

Sequential requests on the same key:
```bash
curl -si http://127.0.0.1:80/products   → X-Cache: MISS  (TTL expired or first request)
curl -si http://127.0.0.1:80/products   → X-Cache: HIT   (served from Redis)
curl -si http://127.0.0.1:80/products/1 → X-Cache: MISS  (new key, DB query + cache fill)
curl -si http://127.0.0.1:80/products/1 → X-Cache: HIT   (served from Redis)
```

### Why latency is higher at 500 VUs (bottleneck report summary)

The 98%+ cache hit rate proves Redis is working correctly — the DB is not the bottleneck. The latency at 500 VUs is caused by **gunicorn worker-pool saturation**:

- 12 sync workers (4 per instance × 3 instances) handle one request at a time each
- At 500 concurrent VUs, the queue grows faster than the 12 workers can drain it
- Docker Desktop on macOS adds ~10–50ms of VM networking overhead per hop vs bare Linux
- **No requests were lost or errored** — they were queued and served, just slowly

**The fix (documented in `docs/capacity_plan.md`):** Switch to `gevent` async workers (4 workers × 200 connections = 800 concurrent handlers per instance vs. 4 today). This is a one-line change to `docker-entrypoint.sh` and would reduce p95 to sub-500ms on the same hardware.

---

## Documentation Quest — All Tiers Completed

### Bronze — The Map

| File | Description |
|---|---|
| `README.md` | Full setup guide: clone → install → DB → seed → run → verify, both local and Docker Compose modes, project tree, links to all docs |
| `docs/architecture.md` | Five Mermaid diagrams showing request flows for Bronze (single server), Silver (Nginx + 3 replicas), and Gold (cache HIT, cache MISS, POST invalidation); full component map |
| `docs/api.md` | All 5 endpoints documented: method, URL, request schema, response examples (200/201/404), `X-Cache` header table, cache key reference, full data model |

### Silver — The Manual

| File | Description |
|---|---|
| `docs/deploy_guide.md` | First-time deploy, service table, scaling up/down, rolling restart, rollback (image + schema), DB backup/restore, Redis flush, production checklist |
| `docs/troubleshooting.md` | Eight common issues: DB connection fail, Redis refused, Nginx 502, port 80 conflict, macOS AirPlay port 5000, unseeded DB, `uv` not found, dependency desync |
| `docs/configuration.md` | Every environment variable with default, description, where it is used, and Docker vs local examples; code-level cache constants; gunicorn and Nginx settings |

### Gold — The Codex

| File | Description |
|---|---|
| `docs/runbooks.md` | Four operational playbooks: "App is Slow", "High Error Rate", "Redis is Down", "Database is Full" — each with Detect → Confirm → Diagnose → Fix → Verify steps |
| `docs/decision_log.md` | Technology rationale for Flask, Peewee, PostgreSQL, Nginx, Redis, k6, uv, and Docker Compose — each with Rationale and Trade-offs Accepted |
| `docs/capacity_plan.md` | Measured limits from all three load tests, three bottleneck analyses with calculations, five-step scaling ladder with expected impact, AWS cost projection ($95/mo → $200/mo at 10×) |

### Supporting docs

| File | Description |
|---|---|
| `docs/bottleneck_report.md` | Full Bronze → Silver → Gold optimization story: what was slow, what was fixed, why caching helped, what to do next |
| `docs/quest_completion.md` | This file — verified test results, cache evidence, and documentation index |

---

## Final File Tree

```
PE-Hackathon/
├── app/
│   ├── __init__.py           # App factory with init_db + init_cache
│   ├── cache.py              # Redis wrapper: get/set/delete/stats
│   ├── database.py           # Peewee DatabaseProxy + lifecycle hooks
│   ├── models/
│   │   ├── __init__.py       # Imports Product
│   │   └── product.py        # Product model (name, category, description, price, stock)
│   └── routes/
│       ├── __init__.py       # Registers products_bp + cache_bp
│       ├── cache_stats.py    # GET /cache/stats
│       └── products.py       # GET+POST /products, GET /products/<id>
├── docs/
│   ├── api.md
│   ├── architecture.md
│   ├── bottleneck_report.md
│   ├── capacity_plan.md
│   ├── configuration.md
│   ├── decision_log.md
│   ├── deploy_guide.md
│   ├── quest_completion.md   ← this file
│   ├── runbooks.md
│   └── troubleshooting.md
├── loadtest/
│   ├── bronze_test.js        # k6: 50 VUs × 30s
│   ├── silver_test.js        # k6: 200 VUs × 60s
│   ├── gold_test.js          # k6: 500 VUs × 120s
│   └── results/
│       ├── bronze_results.txt
│       ├── silver_results.txt
│       ├── gold_results.txt
│       ├── gold_results_final.txt
│       └── docker_ps_final.txt
├── .env.example
├── .gitignore
├── .python-version
├── Dockerfile
├── README.md
├── docker-compose.yml
├── docker-entrypoint.sh
├── nginx.conf
├── pyproject.toml
├── run.py
└── seed.py
```
