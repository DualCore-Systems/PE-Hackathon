# Deployment Guide

## Prerequisites

| Tool | Minimum version | Install |
|---|---|---|
| Docker | 24+ | [docs.docker.com](https://docs.docker.com/get-docker/) |
| Docker Compose | v2 (plugin) | bundled with Docker Desktop |
| k6 (load testing) | 0.45+ | `brew install k6` |

---

## First-time Deployment

```bash
# 1. Clone the repository
git clone <repo-url>
cd PE-Hackathon

# 2. Build images and start all services
docker compose up --build -d

# 3. Wait for app1 to finish seeding (~10–15 seconds)
docker compose logs -f app1
# Look for: "Starting Flask with gunicorn..."

# 4. Verify
curl http://127.0.0.1:80/health          # {"status":"ok"}
curl http://127.0.0.1:80/cache/stats     # {"hits":0,"misses":…}
```

---

## Service Overview

| Service | Image | Port (internal) | External port | Role |
|---|---|---|---|---|
| `db` | `postgres:16-alpine` | 5432 | none | Primary database |
| `redis` | `redis:7-alpine` | 6379 | none | Cache + counters |
| `app1` | `pe-hackathon-app1` | 5000 | none | Flask replica; runs seeder |
| `app2` | `pe-hackathon-app2` | 5000 | none | Flask replica |
| `app3` | `pe-hackathon-app3` | 5000 | none | Flask replica |
| `nginx` | `nginx:alpine` | 80 | **80** | Load balancer |

All services share the `pe-hackathon_default` bridge network. Only Nginx is exposed to the host.

---

## Scaling Up and Down

### Horizontal scaling (add more app replicas)

The Flask app is fully stateless — all shared state lives in PostgreSQL and Redis — so you can run any number of replicas.

> **Note:** The current `docker-compose.yml` defines three named services (`app1`, `app2`, `app3`). To add a fourth replica, either add `app4` to the compose file and update `nginx.conf`, or use the approach below with a separate `scale` compose file.

**Quick replica count change via compose override:**

```bash
# Bring up 5 replicas (add to nginx.conf first)
docker compose up -d --scale app1=1 --scale app2=1 --scale app3=1
```

**Adding a permanent fourth replica:**

1. Add `app4` to `docker-compose.yml` (copy an `app2`/`app3` block, no `SEED_DB`).
2. Add `server app4:5000;` to the `upstream flask_app` block in `nginx.conf`.
3. Rebuild and restart:

```bash
docker compose up --build -d
docker compose restart nginx    # picks up new nginx.conf
```

### Scaling down

```bash
# Stop and remove app3 without touching db/redis
docker compose stop app3
docker compose rm -f app3
docker compose restart nginx    # nginx will 502 on app3 upstream until removed from config
```

To prevent 502s, remove `server app3:5000;` from `nginx.conf` before stopping the container.

---

## Rebuilding After Code Changes

```bash
# Rebuild only app images (not postgres/redis/nginx)
docker compose build app1 app2 app3

# Restart apps with zero-downtime rolling restart
docker compose up -d --no-deps app1
sleep 5
docker compose up -d --no-deps app2
sleep 5
docker compose up -d --no-deps app3
```

The 5-second gaps let each instance finish its startup healthcheck before the next rolls.

---

## Environment Variable Changes

To apply an `.env` change or change an environment variable:

```bash
# Edit docker-compose.yml or create a .env file
# Then re-create only the affected services
docker compose up -d --force-recreate app1 app2 app3
```

---

## Rollback

### Roll back to the previous image

```bash
# Tag current image before deploying
docker tag pe-hackathon-app1:latest pe-hackathon-app1:backup

# If the new deploy is bad, restore
docker tag pe-hackathon-app1:backup pe-hackathon-app1:latest
docker compose up -d --no-deps app1 app2 app3
```

### Roll back the database schema

This project uses Peewee with `create_tables(safe=True)` — tables are created idempotently and never automatically dropped. To roll back a schema change:

1. Write a migration script that reverses the change (e.g., `ALTER TABLE product DROP COLUMN foo`).
2. Run it against the database:

```bash
docker exec -it pe-hackathon-db-1 psql -U postgres -d hackathon_db
```

3. Redeploy the old app image.

---

## Database Backup and Restore

### Backup

```bash
docker exec pe-hackathon-db-1 \
  pg_dump -U postgres hackathon_db > backup_$(date +%Y%m%d_%H%M%S).sql
```

### Restore

```bash
# Stop app instances to prevent writes during restore
docker compose stop app1 app2 app3

# Restore
docker exec -i pe-hackathon-db-1 \
  psql -U postgres hackathon_db < backup_20260405_120000.sql

# Restart apps
docker compose start app1 app2 app3
```

---

## Clearing the Redis Cache

Flush all cache keys without restarting Redis:

```bash
docker exec pe-hackathon-redis-1 redis-cli FLUSHDB
```

This resets `cache:hits` and `cache:misses` counters to zero and clears all cached product data. The next request to each endpoint will be a cache MISS.

---

## Stopping and Removing

```bash
# Stop containers, keep volumes (database data survives)
docker compose down

# Stop containers AND remove volumes (wipes database)
docker compose down -v

# Remove images too
docker compose down -v --rmi local
```

---

## Production Checklist

Before deploying to a real server:

- [ ] Set `FLASK_DEBUG=false` (already default in compose)
- [ ] Change `DATABASE_PASSWORD` from `postgres` to a strong random value
- [ ] Move secrets to Docker secrets or a secrets manager (not env vars in compose file)
- [ ] Configure Nginx TLS (add an SSL certificate block to `nginx.conf`)
- [ ] Set `proxy_read_timeout` in `nginx.conf` appropriately for your SLOs
- [ ] Add a Postgres read replica for read-heavy workloads
- [ ] Add PgBouncer between app and Postgres for connection pooling
- [ ] Switch gunicorn worker class to `gevent` for async I/O
- [ ] Set up log shipping (Loki, Papertrail, etc.)
- [ ] Configure Redis `maxmemory` and `maxmemory-policy allkeys-lru`
