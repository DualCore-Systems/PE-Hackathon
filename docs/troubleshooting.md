# Troubleshooting

---

## Database Connection Fails

### Symptom

```
psycopg2.OperationalError: could not connect to server: Connection refused
```
or the container log shows:
```
app1-1 | postgres not ready, retrying in 1s...
```

### Causes and fixes

**1. PostgreSQL container is not running**

```bash
docker compose ps db
# If status is not "Up (healthy)", start it:
docker compose up -d db
docker compose logs db
```

**2. Database credentials mismatch**

Compare the values in your `.env` (or `docker-compose.yml` environment block) against what PostgreSQL was initialized with. If the container already exists with a different password, you must remove the volume and recreate:

```bash
docker compose down -v      # removes pgdata volume
docker compose up -d        # reinitializes with current credentials
```

**3. Wrong host for local dev**

When running `uv run run.py` locally, `DATABASE_HOST` must be `localhost` (or `127.0.0.1`), not `db`. The hostname `db` only resolves inside the Docker Compose network.

```bash
# .env for local dev
DATABASE_HOST=localhost

# docker-compose.yml for containerized apps
DATABASE_HOST: db
```

**4. Port 5432 already in use**

Another PostgreSQL instance is running on port 5432. Either stop it or change the host mapping in `docker-compose.yml`:

```yaml
ports:
  - "5433:5432"   # expose on 5433 instead
```

Then update `DATABASE_PORT=5433` in your `.env`.

---

## Redis Connection Refused

### Symptom

```
redis.exceptions.ConnectionError: Error 111 connecting to localhost:6379. Connection refused.
```

Or `/cache/stats` returns:
```json
{"error": "cache unavailable: Connection refused"}
```

### Causes and fixes

**1. Redis container is not running**

```bash
docker compose ps redis
docker compose up -d redis
docker compose logs redis
```

**2. Wrong REDIS_HOST for local dev**

When running locally (outside Docker), Redis must be accessible on `localhost`. If you started Redis via Docker Compose, it binds only to the internal network by default. Expose it:

```bash
# Quick fix: expose redis on host port 6379
docker run -d -p 6379:6379 redis:7-alpine
```

Or add a `ports` block to the `redis` service in `docker-compose.yml`:

```yaml
redis:
  image: redis:7-alpine
  ports:
    - "6379:6379"
```

**3. Cache errors are silent by design**

The app catches all Redis exceptions and falls back to querying the database directly. If you see `X-Cache: MISS` on every request and `/cache/stats` returns an error, Redis is down but the app is still serving traffic correctly. Fix Redis and the cache will resume automatically.

---

## Nginx Returns 502 Bad Gateway

### Symptom

```bash
curl http://127.0.0.1:80/health
# <html>...502 Bad Gateway...</html>
```

### Causes and fixes

**1. All app containers are down**

```bash
docker compose ps
docker compose up -d app1 app2 app3
```

**2. App containers are starting up (race condition)**

The `docker-entrypoint.sh` waits for PostgreSQL and Redis before starting gunicorn. If startup takes longer than expected, Nginx may return 502 while waiting. Wait 15–20 seconds and retry.

**3. App crashed after startup**

```bash
docker compose logs app1 --tail=50
# Look for Python tracebacks
```

Common cause: a syntax error in recently edited code. Fix the error and rebuild:

```bash
docker compose build app1 app2 app3
docker compose up -d app1 app2 app3
```

**4. Nginx upstream is misconfigured**

Check `nginx.conf` — the `upstream flask_app` block must list the correct service names and port:

```nginx
upstream flask_app {
    server app1:5000;
    server app2:5000;
    server app3:5000;
}
```

Service names must match the keys in `docker-compose.yml`.

---

## Port 80 Already in Use

### Symptom

```
Error response from daemon: driver failed programming external connectivity ...
Bind for 0.0.0.0:80 failed: port is already allocated
```

### Fix

Find and stop the process using port 80:

```bash
sudo lsof -i :80
# Kill the PID or stop the service, then:
docker compose up -d nginx
```

Or change the external port in `docker-compose.yml`:

```yaml
nginx:
  ports:
    - "8080:80"   # access via http://127.0.0.1:8080
```

---

## Port 5000 Returns Wrong Response (macOS)

### Symptom

```bash
curl http://localhost:5000/health
# HTTP/1.1 403 Forbidden
# Server: AirTunes/925.5.1
```

### Cause

macOS AirPlay Receiver claims port 5000 on the IPv6 loopback (`[::1]`). `curl localhost:5000` resolves to IPv6 first and hits AirPlay instead of Flask.

### Fix

Always use the explicit IPv4 address for local development:

```bash
curl http://127.0.0.1:5000/health   # ✓ IPv4 — hits Flask
curl http://localhost:5000/health   # ✗ IPv6 — hits AirPlay on macOS
```

Or disable AirPlay Receiver in **System Settings → General → AirDrop & Handoff**.

---

## Database Was Not Seeded

### Symptom

```bash
curl http://127.0.0.1:80/products
# []
```

### Fix

The seeder runs only in `app1` (controlled by `SEED_DB=true`). Check the log:

```bash
docker compose logs app1 | grep -E "Seed|product"
```

If the log shows "Database already has 0 products — skipping seed", the check ran before the table existed. Destroy and recreate the volume:

```bash
docker compose down -v
docker compose up -d
```

To re-seed a running cluster without recreating volumes:

```bash
docker compose exec app1 uv run python seed.py
```

---

## `uv` Command Not Found

### Fix

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc   # or restart your shell

# Verify
uv --version
```

---

## Dependencies Out of Sync

### Symptom

```
ModuleNotFoundError: No module named 'redis'
```

### Fix

```bash
uv sync          # re-installs all deps from uv.lock
```

If the lock file itself is stale after editing `pyproject.toml`:

```bash
uv lock          # regenerates uv.lock
uv sync          # installs from the new lock
```

For Docker images, rebuild:

```bash
docker compose build --no-cache app1 app2 app3
```

---

## High Memory Usage in Containers

### Symptom

Container OOM-killed; `docker stats` shows memory climbing.

### Causes and fixes

**Gunicorn worker count too high:** Each sync worker is a full Python process. With 4 workers and a typical Flask app, expect ~150–200 MB per replica. With 3 replicas, that's ~600 MB total for the app tier. Reduce workers if memory is constrained:

```bash
# In docker-entrypoint.sh
--workers 2    # instead of 4
```

**Redis unbounded memory:** Redis has no memory limit by default. Add limits:

```yaml
# docker-compose.yml
redis:
  command: redis-server --maxmemory 128mb --maxmemory-policy allkeys-lru
```

---

## Viewing Logs

```bash
# All services
docker compose logs -f

# Specific service, last 100 lines
docker compose logs --tail=100 app1

# Nginx access log
docker compose logs nginx

# PostgreSQL query log (requires log_statement=all in pg config)
docker compose logs db
```
