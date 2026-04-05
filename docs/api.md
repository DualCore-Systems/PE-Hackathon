# API Reference

**Base URL (local dev):** `http://127.0.0.1:5000`  
**Base URL (Docker Compose):** `http://127.0.0.1:80`

All responses are `Content-Type: application/json`.  
All `GET` endpoints that hit the cache include an `X-Cache: HIT | MISS` response header.

---

## GET /health

Liveness check. Returns immediately without touching the database or cache.

### Request

```
GET /health
```

### Response `200 OK`

```json
{"status": "ok"}
```

### Example

```bash
curl http://127.0.0.1:80/health
```

---

## GET /health/ready

Readiness check. Verifies that both PostgreSQL and Redis are reachable. Use this to confirm the app can actually serve traffic, not just that the process is running.

### Request

```
GET /health/ready
```

### Response `200 OK` (all dependencies healthy)

```json
{
  "status": "ok",
  "checks": {
    "database": "ok",
    "cache": "ok"
  }
}
```

### Response `503 Service Unavailable` (one or more dependencies down)

```json
{
  "status": "degraded",
  "checks": {
    "database": "ok",
    "cache": "error: Connection refused"
  }
}
```

### Example

```bash
curl http://127.0.0.1:80/health/ready
```

---

## GET /metrics

Exposes application metrics in Prometheus text format. Scraped by Prometheus every 5 seconds.

### Request

```
GET /metrics
```

### Response `200 OK`

Returns Prometheus exposition format (`text/plain`). Key metrics:

| Metric | Type | Description |
|---|---|---|
| `http_requests_total` | Counter | Total requests by method, endpoint, status |
| `http_request_duration_seconds` | Histogram | Request latency (p50/p95/p99) |
| `http_errors_total` | Counter | 4xx and 5xx responses |
| `app_up` | Gauge | 1 if the app is running |
| `app_start_time_seconds` | Gauge | Unix timestamp of app start |

### Example

```bash
curl http://127.0.0.1:80/metrics | grep http_requests_total
```

---

## GET /products

Returns all products ordered by `id` ascending. Response is cached in Redis for 60 seconds.

### Request

```
GET /products
```

### Response `200 OK`

```json
[
  {
    "id": 1,
    "name": "Premium Pack 1",
    "category": "Food",
    "description": "A high-quality premium pack 1 for everyday use.",
    "price": "131.92",
    "stock": 311
  },
  {
    "id": 2,
    "name": "Classic Widget 2",
    "category": "Electronics",
    "description": "A high-quality classic widget 2 for everyday use.",
    "price": "45.99",
    "stock": 87
  }
]
```

### Response Headers

| Header | Values | Description |
|---|---|---|
| `X-Cache` | `HIT` \| `MISS` | Whether the response was served from Redis |

### Notes

- No pagination. All products are returned in a single response.
- The list cache key (`products:all`) is invalidated on every `POST /products`.
- First request after startup or after the 60s TTL expires will be a `MISS` and will hit PostgreSQL.

### Example

```bash
# First request — MISS (hits DB)
curl -i http://127.0.0.1:80/products | grep X-Cache
# X-Cache: MISS

# Second request within 60s — HIT (served from Redis)
curl -i http://127.0.0.1:80/products | grep X-Cache
# X-Cache: HIT
```

---

## POST /products

Creates a new product. Invalidates the `GET /products` list cache.

### Request

```
POST /products
Content-Type: application/json
```

**Body** (all fields required except `description`):

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Product name |
| `category` | string | yes | Product category |
| `description` | string | no | Optional longer description |
| `price` | number | yes | Unit price (stored with 2 decimal places) |
| `stock` | integer | yes | Quantity in stock |

```json
{
  "name": "Wireless Keyboard",
  "category": "Electronics",
  "description": "Compact Bluetooth keyboard with 3-device pairing.",
  "price": 49.99,
  "stock": 120
}
```

### Response `201 Created`

Returns the newly created product including its assigned `id`.

```json
{
  "id": 101,
  "name": "Wireless Keyboard",
  "category": "Electronics",
  "description": "Compact Bluetooth keyboard with 3-device pairing.",
  "price": 49.99,
  "stock": 120
}
```

### Side effects

- Inserts one row into the `product` table.
- Calls `DEL products:all` on Redis — the next `GET /products` will be a cache MISS.
- Does **not** invalidate individual product keys (those are set lazily on first read).

### Example

```bash
curl -X POST http://127.0.0.1:80/products \
  -H "Content-Type: application/json" \
  -d '{"name":"Wireless Keyboard","category":"Electronics","price":49.99,"stock":120}'
```

---

## GET /products/\<id\>

Returns a single product by its primary key. Response is cached in Redis for 60 seconds.

### Request

```
GET /products/<id>
```

| Parameter | Type | Description |
|---|---|---|
| `id` | integer | Product primary key |

### Response `200 OK`

```json
{
  "id": 42,
  "name": "Smart Widget 42",
  "category": "Food",
  "description": "A high-quality smart widget 42 for everyday use.",
  "price": "187.29",
  "stock": 240
}
```

### Response `404 Not Found`

```json
{"error": "not found"}
```

### Response Headers

| Header | Values | Description |
|---|---|---|
| `X-Cache` | `HIT` \| `MISS` | Whether the response was served from Redis |

### Cache key

```
products:<id>       # e.g., products:42
```

Each product ID has its own cache entry. Cache key is set on first read and expires after 60 seconds.

### Example

```bash
# Get product 42
curl -i http://127.0.0.1:80/products/42

# Show cache header
curl -si http://127.0.0.1:80/products/42 | grep X-Cache
```

---

## GET /cache/stats

Returns the accumulated cache hit/miss counts stored in Redis. Counters are shared across all app replicas — the numbers reflect the total across the whole cluster.

### Request

```
GET /cache/stats
```

### Response `200 OK` — normal operation

```json
{
  "hits": 64680,
  "misses": 1288,
  "total_requests": 65968,
  "hit_rate": "98.0%"
}
```

| Field | Type | Description |
|---|---|---|
| `hits` | integer | Total cache hits since Redis started (or since last `FLUSHDB`) |
| `misses` | integer | Total cache misses |
| `total_requests` | integer | `hits + misses` |
| `hit_rate` | string | Percentage, formatted to 1 decimal place |

### Response `200 OK` — Redis unavailable

```json
{"error": "cache unavailable: Connection refused"}
```

The endpoint never returns a non-200 status, even when Redis is down. Check the `error` field.

### Notes

- Counters are stored in Redis keys `cache:hits` and `cache:misses` using atomic `INCR`.
- Counters persist across app restarts (they live in Redis, not in-process).
- Counters reset when Redis restarts or when you run `docker compose down -v`.
- The `hit_rate` field returns `"N/A"` when `total_requests` is 0.

### Example

```bash
curl http://127.0.0.1:80/cache/stats | python3 -m json.tool
```

---

## Error Handling Summary

| Scenario | Status | Body |
|---|---|---|
| Product not found | `404` | `{"error": "not found"}` |
| Missing required field on POST | `400` | `{"error": "validation failed", "details": ["'name' is required", ...]}` |
| Invalid field type/value on POST | `400` | `{"error": "validation failed", "details": ["'price' must be a number"]}` |
| Invalid or missing JSON body | `400` | `{"error": "invalid or missing JSON body"}` |
| Unknown route | `404` | `{"error": "not found", "message": "/path does not exist"}` |
| Wrong HTTP method | `405` | `{"error": "method not allowed", "message": "DELETE is not allowed on /products"}` |
| Database unreachable | `500` | `{"error": "internal server error", "message": "an unexpected error occurred"}` |
| Redis unreachable | `200` | Cache fails silently; DB is queried instead |

> All error responses return structured JSON — no HTML tracebacks are ever exposed to clients. Redis errors are intentionally swallowed — the app degrades gracefully to direct DB reads when Redis is unavailable.

---

## Data Model

### Product

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | integer | PK, auto-increment | Primary key |
| `name` | varchar | NOT NULL | Product display name |
| `category` | varchar | NOT NULL | Product category string |
| `description` | text | nullable | Optional long description |
| `price` | decimal(10,2) | NOT NULL | Unit price |
| `stock` | integer | NOT NULL | Available quantity |

### Cache Keys

| Key | Type | TTL | Content |
|---|---|---|---|
| `products:all` | string (JSON) | 60s | Serialized `GET /products` array |
| `products:<id>` | string (JSON) | 60s | Serialized single product object |
| `cache:hits` | integer | none | Cumulative hit counter |
| `cache:misses` | integer | none | Cumulative miss counter |
