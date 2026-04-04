# Configuration Reference

All configuration is done via environment variables. For local development, set them in `.env` (copied from `.env.example`). For Docker Compose, set them in the `environment:` block of each service.

---

## Loading Order

1. `.env` file is loaded by `python-dotenv` at app startup (`load_dotenv()` in `create_app()`).
2. Environment variables already set in the shell or Docker override `.env` values.
3. Hard-coded defaults in `app/database.py` and `app/cache.py` are the final fallback.

---

## Database Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_NAME` | `hackathon_db` | PostgreSQL database name |
| `DATABASE_HOST` | `localhost` | PostgreSQL host. Use `db` inside Docker Compose. |
| `DATABASE_PORT` | `5432` | PostgreSQL port |
| `DATABASE_USER` | `postgres` | PostgreSQL username |
| `DATABASE_PASSWORD` | `postgres` | PostgreSQL password. **Change this in production.** |

**Where used:** `app/database.py` → `init_db()`

**Example (local dev):**
```env
DATABASE_NAME=hackathon_db
DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_USER=postgres
DATABASE_PASSWORD=postgres
```

**Example (Docker Compose):**
```yaml
DATABASE_HOST: db        # service name in compose network
DATABASE_PORT: 5432
DATABASE_NAME: hackathon_db
DATABASE_USER: postgres
DATABASE_PASSWORD: postgres
```

---

## Redis Variables

| Variable | Default | Description |
|---|---|---|
| `REDIS_HOST` | `localhost` | Redis host. Use `redis` inside Docker Compose. |
| `REDIS_PORT` | `6379` | Redis port |

**Where used:** `app/cache.py` → `init_cache()`

The Redis connection pool is configured with:
- `max_connections=30` (per worker process)
- `socket_connect_timeout=2s`
- `socket_timeout=2s`

These values are hard-coded in `app/cache.py`. Failures are caught silently — if Redis is unreachable, the app falls back to direct database reads.

**Example (local dev):**
```env
REDIS_HOST=localhost
REDIS_PORT=6379
```

**Example (Docker Compose):**
```yaml
REDIS_HOST: redis
REDIS_PORT: 6379
```

---

## Flask Variables

| Variable | Default | Description |
|---|---|---|
| `FLASK_DEBUG` | `false` | Enables Flask debug mode and the Werkzeug reloader. **Never enable in production.** |

**Where used:** Flask internals via `FLASK_DEBUG` environment variable.

> When `FLASK_DEBUG=true`, the app runs the single-threaded Werkzeug dev server via `run.py`. In Docker Compose, `FLASK_DEBUG` is always `false` and gunicorn is used instead.

---

## Seeding Variable

| Variable | Default | Description |
|---|---|---|
| `SEED_DB` | (unset) | Set to `"true"` to run `seed.py` on container startup. Only `app1` has this set. |

**Where used:** `docker-entrypoint.sh`

The seed script (`seed.py`) is idempotent: it checks `Product.select().count() > 0` and skips if data already exists. Setting `SEED_DB=true` on multiple replicas is safe but wasteful.

---

## Cache Settings (code-level, not env vars)

These are constants in `app/cache.py` that can be changed in code but are not currently exposed as environment variables:

| Constant | Value | Description |
|---|---|---|
| `CACHE_TTL` | `60` | Seconds before a cached product entry expires |
| `PRODUCTS_ALL_KEY` | `"products:all"` | Redis key for the full product list |
| `PRODUCT_KEY` | `"products:{id}"` | Redis key template for a single product |
| `HIT_COUNTER` | `"cache:hits"` | Redis key storing cumulative hit count |
| `MISS_COUNTER` | `"cache:misses"` | Redis key storing cumulative miss count |

To expose `CACHE_TTL` as an env var, change `app/cache.py`:

```python
CACHE_TTL = int(os.environ.get("CACHE_TTL", 60))
```

---

## Gunicorn Settings (entrypoint-level)

Set in `docker-entrypoint.sh`. Not environment variables — change the script and rebuild.

| Setting | Current value | Description |
|---|---|---|
| `--workers` | `4` | Number of worker processes per replica |
| `--timeout` | `120` | Worker timeout in seconds (kills slow workers) |
| `--bind` | `0.0.0.0:5000` | Listen address inside the container |

**Formula for worker count:** `2 × CPU_cores + 1` is the gunicorn recommendation for sync workers. For I/O-bound workloads behind Redis (most requests are cache HITs), consider `gevent` workers instead.

---

## Nginx Settings

Configured in `nginx.conf` (not environment variables). Key values:

| Setting | Value | Description |
|---|---|---|
| `keepalive 32` | 32 | Persistent connections to upstream workers |
| `keepalive_timeout 65` | 65s | How long to keep idle client connections open |
| `proxy_connect_timeout` | 10s | Timeout to establish connection to upstream |
| `proxy_read_timeout` | 60s | Timeout to receive a response from upstream |
| `client_max_body_size` | 1m | Maximum request body size |

---

## Full `.env` Template

```env
# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_NAME=hackathon_db
DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_USER=postgres
DATABASE_PASSWORD=postgres

# ── Redis ─────────────────────────────────────────────────────────────────────
REDIS_HOST=localhost
REDIS_PORT=6379

# ── Flask ─────────────────────────────────────────────────────────────────────
FLASK_DEBUG=true
```

> Copy `.env.example` to `.env` and edit as needed. The `.env` file is git-ignored.
