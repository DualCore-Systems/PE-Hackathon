# Architecture

## Overview

The system is a horizontally-scaled Flask API behind Nginx, backed by PostgreSQL for persistence and Redis for read-through caching.

Three deployment modes are supported:

| Mode | Command | Use case |
|---|---|---|
| Local dev | `uv run run.py` | Single Flask process, no containers |
| Full stack | `docker compose up` | Nginx + 3 replicas + Postgres + Redis |
| Custom scale | `docker compose up --scale app1=N` | Adjust replica count |

---

## Bronze — Local Dev (no cache)

```mermaid
sequenceDiagram
    participant Client
    participant Flask as Flask (werkzeug dev server)
    participant PG as PostgreSQL

    Client->>Flask: GET /products
    Flask->>PG: SELECT * FROM product ORDER BY id
    PG-->>Flask: 100 rows
    Flask-->>Client: 200 OK  [X-Cache: MISS]

    Client->>Flask: GET /products/42
    Flask->>PG: SELECT * FROM product WHERE id=42
    PG-->>Flask: 1 row
    Flask-->>Client: 200 OK  [X-Cache: MISS]
```

**Bottleneck:** Single-threaded werkzeug server; every request waits in line.

---

## Silver — Docker Compose (Nginx + 3 × Gunicorn, no cache)

```mermaid
graph LR
    U[User / k6] -->|HTTP :80| N[Nginx<br/>round-robin]

    N -->|:5000| A1[app1<br/>gunicorn 4w]
    N -->|:5000| A2[app2<br/>gunicorn 4w]
    N -->|:5000| A3[app3<br/>gunicorn 4w]

    A1 & A2 & A3 -->|SQL| PG[(PostgreSQL 16)]

    style N fill:#009639,color:#fff
    style PG fill:#336791,color:#fff
```

**Capacity:** 4 workers × 3 instances = 12 concurrent request handlers.  
**Throughput observed:** ~163 RPS at 200 VUs.

---

## Gold — Full Stack with Redis Cache

### Request flow — cache HIT (steady state, ~98% of requests)

```mermaid
sequenceDiagram
    participant Client
    participant Nginx
    participant App as Flask / Gunicorn
    participant Redis
    participant PG as PostgreSQL

    Client->>Nginx: GET /products/42
    Nginx->>App: proxy (round-robin)
    App->>Redis: GET products:42
    Redis-->>App: JSON payload (cache HIT)
    App-->>Nginx: 200 OK  X-Cache: HIT
    Nginx-->>Client: 200 OK  X-Cache: HIT

    Note over Redis,PG: DB is never touched on a HIT
```

### Request flow — cache MISS (first request or TTL expired)

```mermaid
sequenceDiagram
    participant Client
    participant Nginx
    participant App as Flask / Gunicorn
    participant Redis
    participant PG as PostgreSQL

    Client->>Nginx: GET /products/42
    Nginx->>App: proxy (round-robin)
    App->>Redis: GET products:42
    Redis-->>App: nil (cache MISS)
    App->>PG: SELECT * FROM product WHERE id=42
    PG-->>App: 1 row
    App->>Redis: SETEX products:42 60 <json>
    App-->>Nginx: 200 OK  X-Cache: MISS
    Nginx-->>Client: 200 OK  X-Cache: MISS
```

### POST (write-through invalidation)

```mermaid
sequenceDiagram
    participant Client
    participant App as Flask / Gunicorn
    participant Redis
    participant PG as PostgreSQL

    Client->>App: POST /products  {name, category, price, stock}
    App->>PG: INSERT INTO product …
    PG-->>App: new row
    App->>Redis: DEL products:all
    App-->>Client: 201 Created  {id, name, …}
```

---

## Component Map

```mermaid
graph TB
    subgraph Host["Docker Host (or macOS)"]
        subgraph Compose["docker-compose network"]
            N[nginx:alpine<br/>:80→:80]

            subgraph Apps["Flask Replicas"]
                A1[app1<br/>gunicorn :5000<br/>SEED_DB=true]
                A2[app2<br/>gunicorn :5000]
                A3[app3<br/>gunicorn :5000]
            end

            R[(redis:7-alpine<br/>:6379)]
            DB[(postgres:16-alpine<br/>:5432)]
            VOL[pgdata volume]
        end
    end

    N -->|round-robin| A1 & A2 & A3
    A1 & A2 & A3 -->|cache-aside| R
    A1 & A2 & A3 -->|SQL via psycopg2| DB
    DB --- VOL

    style N fill:#009639,color:#fff
    style R fill:#DC382D,color:#fff
    style DB fill:#336791,color:#fff
    style VOL fill:#aaa,color:#000
```

---

## Key Design Decisions

| Component | Choice | Why |
|---|---|---|
| Load balancer | Nginx round-robin | Stateless replicas; no session affinity needed |
| App server | Gunicorn gevent workers | Async I/O handles ~200 concurrent connections per worker vs sync's 1 |
| Cache | Redis (shared) | All 3 replicas read the same key space; counters are atomic |
| Cache TTL | 60 seconds | Balance between freshness and hit rate; adjustable via `CACHE_TTL` in `app/cache.py` |
| DB persistence | pgdata named volume | Survives `docker compose down`; removed only with `down -v` |
| Seed ownership | app1 only (`SEED_DB=true`) | Prevents duplicate inserts on parallel startup |

| Monitoring | Prometheus + Grafana | Industry-standard observability stack; free, self-hosted |
| Alerting | Alertmanager + Discord | Fires alerts within 30s; routes to Discord for team notifications |
| Logging | Structured JSON (pythonjsonlogger) | Machine-parseable; includes timestamp, level, component, latency |
| Testing | pytest + pytest-cov (88%) | In-memory SQLite for fast tests; CI gate at 70% coverage |

See [docs/decision_log.md](decision_log.md) for the full rationale on each choice.

---

## Monitoring Stack

```mermaid
graph LR
    A1[App 1] & A2[App 2] & A3[App 3] -->|/metrics| P[Prometheus :9090]
    P -->|queries| G[Grafana :3001]
    P -->|alert rules| AM[Alertmanager :9093]
    AM -->|webhook| DW[Discord]

    style P fill:#E6522C,color:#fff
    style G fill:#F46800,color:#fff
    style AM fill:#E6522C,color:#fff
    style DW fill:#5865F2,color:#fff
```

**Four Golden Signals tracked on the Grafana dashboard:**

| Signal | Metric | Panel |
|---|---|---|
| **Latency** | `http_request_duration_seconds` (p50/p95/p99) | Line chart |
| **Traffic** | `rate(http_requests_total[1m])` | Line chart |
| **Errors** | `http_errors_total / http_requests_total` | Line chart with thresholds |
| **Saturation** | `count(up{job="flask-app"} == 1)` | Stat panel (healthy instances) |
