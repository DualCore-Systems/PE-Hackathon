# Failure Mode Documentation

What happens when things break — and how the system responds.

---

## 1. Application Container Crash

**Trigger:** App process killed (`docker kill <container>`) or OOM.

**Behavior:**
- Docker `restart: always` policy automatically restarts the container
- Nginx routes traffic to the remaining 2 healthy replicas during restart (~2–5 seconds)
- No data loss — PostgreSQL and Redis are separate services
- The restarted container rejoins the Nginx upstream pool automatically

**User impact:** Brief latency spike; no errors if other replicas are healthy.

**Demo:**
```bash
# Kill a container
docker kill pe-hackathon-main-app1-1

# Watch it come back (within seconds)
docker ps --filter name=app1 --format "{{.Names}} {{.Status}}"

# Verify the system still responds
curl http://127.0.0.1:80/health
```

---

## 2. Database (PostgreSQL) Goes Down

**Trigger:** `docker kill pe-hackathon-main-db-1` or disk full.

**Behavior:**
- Cached GET requests still served from Redis (cache-aside pattern)
- Uncached GET requests and all POST requests return `500 Internal Server Error` with a clean JSON body:
  ```json
  {"error": "internal server error", "message": "an unexpected error occurred"}
  ```
- No stack traces or raw HTML exposed to clients
- Docker `restart: always` brings the DB back; `pgdata` volume preserves all data

**User impact:** Reads may still work (if cached). Writes fail until DB recovers.

---

## 3. Cache (Redis) Goes Down

**Trigger:** `docker kill pe-hackathon-main-redis-1` or memory exhaustion.

**Behavior:**
- **Graceful degradation** — the `cache_get` / `cache_set` / `cache_delete` functions catch all Redis exceptions silently
- All requests fall back to direct PostgreSQL queries
- `X-Cache` header shows `MISS` on every response
- `/cache/stats` returns `{"error": "cache unavailable: ..."}`
- Performance drops (every request hits DB) but **zero errors**
- Docker `restart: always` brings Redis back; cache rebuilds organically as requests arrive

**User impact:** Slower responses. No errors. No data loss.

---

## 4. Nginx Load Balancer Goes Down

**Trigger:** `docker kill pe-hackathon-main-nginx-1`.

**Behavior:**
- All external traffic stops (port 80 unreachable)
- App containers and DB/Redis continue running normally
- Docker `restart: always` restores Nginx within seconds
- No data loss

**User impact:** Complete outage until Nginx restarts (~2–5 seconds).

---

## 5. Bad / Malicious Input

**Trigger:** Client sends invalid JSON, missing fields, wrong types, or garbage data.

**Behavior — POST /products:**

| Input | Response |
|---|---|
| No JSON body | `400` — `{"error": "invalid or missing JSON body"}` |
| Missing required fields | `400` — `{"error": "validation failed", "details": ["'name' is required", ...]}` |
| Empty string for name | `400` — `{"error": "validation failed", "details": ["'name' must be a non-empty string"]}` |
| Negative price | `400` — `{"error": "validation failed", "details": ["'price' must be >= 0"]}` |
| `"price": "free"` | `400` — `{"error": "validation failed", "details": ["'price' must be a number"]}` |
| Negative stock | `400` — `{"error": "validation failed", "details": ["'stock' must be >= 0"]}` |

**Behavior — GET endpoints:**

| Input | Response |
|---|---|
| `GET /products/99999` | `404` — `{"error": "not found"}` |
| `GET /nonexistent` | `404` — `{"error": "not found", "message": "/nonexistent does not exist"}` |
| `DELETE /products` | `405` — `{"error": "method not allowed", "message": "DELETE is not allowed on /products"}` |

**Key principle:** The app never crashes, never leaks stack traces, and always returns structured JSON errors.

---

## 6. All App Replicas Down Simultaneously

**Trigger:** All three app containers crash at the same time.

**Behavior:**
- Nginx returns `502 Bad Gateway` (no upstream available)
- Docker `restart: always` restarts all containers
- First container to restart (`app1` with `SEED_DB=true`) verifies database tables exist
- Service fully recovers in 10–15 seconds

**User impact:** ~10–15 second outage.

---

## Summary — Failure Matrix

| Component | Auto-Restart | Data Loss | Errors During Outage | Recovery Time |
|---|---|---|---|---|
| App container (1 of 3) | Yes | None | None (other replicas serve) | ~2–5s |
| All app containers | Yes | None | 502 until restart | ~10–15s |
| PostgreSQL | Yes | None (volume) | Writes fail; cached reads work | ~5–10s |
| Redis | Yes | Cache only | None (graceful fallback to DB) | ~3–5s |
| Nginx | Yes | None | Complete outage | ~2–5s |
| Bad input | N/A | None | Clean 400 JSON response | Instant |
