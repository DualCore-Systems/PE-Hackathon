# Decision Log

Architectural and technology decisions, recorded with context so future maintainers understand not just what was chosen but why — and what the trade-offs were.

---

## Flask (web framework)

**Decision:** Use Flask over FastAPI, Django, or other Python web frameworks.

**Rationale:**
- Flask has near-zero setup cost for a hackathon: one file, one function, one `@app.route` decorator and you're serving HTTP.
- The request model (one Python function per route, synchronous by default) is immediately readable to anyone who knows Python.
- Flask's `create_app()` factory pattern integrates cleanly with Peewee's `DatabaseProxy` — the database is initialized once per process, not once per import.
- FastAPI would be the better choice for a production async API, but its Pydantic model definitions and async boilerplate add cognitive overhead in a time-constrained hackathon.

**Trade-offs accepted:**
- Flask's built-in dev server is single-threaded (addressed by gunicorn in Silver tier).
- No built-in async support — using `gevent` workers would be the next step for high-concurrency production deployments.
- No built-in input validation — `POST /products` trusts the JSON body fields. A production version would add Marshmallow or Pydantic validation.

---

## Peewee (ORM)

**Decision:** Use Peewee over SQLAlchemy or raw psycopg2.

**Rationale:**
- Peewee's `Model` class maps directly to a table with minimal syntax. Adding a model is 5 lines.
- `model_to_dict()` from `playhouse.shortcuts` converts any model instance to a JSON-serializable dict in one call — exactly what API route handlers need.
- Peewee's `DatabaseProxy` supports late binding: you define models before you know the connection string, and bind the real database at startup. This makes the `create_app()` factory pattern work cleanly.
- SQLAlchemy's power (sessions, unit of work, advanced join expressions) would be overkill here and add hundreds of lines of setup.

**Trade-offs accepted:**
- Peewee opens a new database connection per request (in `before_request`) and closes it in `teardown_appcontext`. Under high concurrency, this creates connection churn. The fix is PgBouncer (connection pooler) between gunicorn and PostgreSQL.
- Peewee has less community momentum than SQLAlchemy — fewer StackOverflow answers, fewer plugins.

---

## PostgreSQL (database)

**Decision:** Use PostgreSQL 16 over SQLite or MySQL.

**Rationale:**
- PostgreSQL is the standard choice for Python web applications. `psycopg2` is the most battle-tested Python Postgres driver.
- PostgreSQL handles concurrent reads and writes correctly with MVCC — important once we have 3 Flask replicas all writing.
- SQLite does not support concurrent writes from multiple processes, which would break the 3-replica setup immediately.
- The `postgres:16-alpine` Docker image is small (~50MB) and starts in under 2 seconds.

**Trade-offs accepted:**
- PostgreSQL requires a separate process (not embedded like SQLite), adding operational complexity for local dev. Mitigated by the one-liner Docker setup.

---

## Nginx (load balancer)

**Decision:** Use Nginx with round-robin upstream instead of HAProxy, Traefik, or a cloud load balancer.

**Rationale:**
- Nginx's `upstream` block with `server` directives is the simplest possible load balancer configuration — 6 lines of config.
- Round-robin is the correct algorithm when all replicas are identical and stateless. Weighted or least-connections would add complexity with no benefit here.
- `keepalive 32` on the upstream reuses TCP connections to gunicorn workers, reducing connection setup overhead per request (measurably improves p95 at high concurrency).
- Traefik would provide automatic service discovery and a dashboard, but requires Docker labels on every service and has a steeper learning curve.

**Trade-offs accepted:**
- Nginx does not perform active health checks on upstreams out of the box (requires the `nginx-plus` upstream module or a custom Lua script). If one app replica crashes, Nginx will route ~33% of requests to it and return 502s until the upstream is manually removed. In production, use a cloud load balancer or Traefik for automatic health-based routing.
- Round-robin does not account for in-flight request depth. If one replica is slower (e.g., doing a cache miss while the others serve cache HITs), it will still receive 1/3 of traffic. Least-connections would be better in that scenario.

---

## Redis (caching)

**Decision:** Use Redis as a shared cache across all replicas, with cache-aside pattern and 60-second TTL.

**Rationale:**
- Redis is the standard shared cache for multi-process Python web applications. It is fast (sub-millisecond single-key reads on localhost), simple to operate, and supports atomic operations (`INCR`) for shared counters.
- A shared external cache (vs. in-process dict) is essential with 3 replicas — an in-process cache would mean each replica caches independently, and `POST /products` would only invalidate the cache on one of the three.
- Cache-aside (read-through on demand, write-invalidate on mutation) is the simplest correct caching pattern for a read-heavy, occasionally-written dataset.
- TTL of 60 seconds was chosen empirically: long enough to absorb the burst of a load test (100 products cached for 60s = at most 1 DB query per product per minute), short enough that product changes are visible within 1 minute.

**Trade-offs accepted:**
- The 60-second TTL means product changes via `POST /products` are invisible to `GET /products/:id` (individual product cache) for up to 60 seconds. The list cache (`products:all`) is invalidated immediately on POST, but individual product caches are not. This is acceptable for a read-heavy catalog.
- Redis is a single point of failure. The app handles Redis downtime gracefully (falls back to DB), but cache stats become unavailable and DB load spikes.

---

## k6 (load testing)

**Decision:** Use k6 over Apache JMeter, Locust, or wrk.

**Rationale:**
- k6 scripts are JavaScript — readable, version-controlled alongside the app, and easy to review in a PR.
- k6 has first-class support for custom metrics (`Trend`, `Rate`, `Counter`), which let us track per-endpoint latency and cache hit rate as named metrics rather than parsing log output.
- k6's `stages` API (ramp up, sustain, ramp down) maps directly to the load test scenarios in this quest (Bronze: 50 VUs flat; Silver: 200 VUs flat; Gold: 500 VUs with ramp).
- `handleSummary()` lets us write a custom human-readable report to the terminal and save it to a file without post-processing.
- JMeter's XML-based configuration is verbose and hard to diff. Locust requires Python and a running Locust server. wrk is fast but has limited scripting support.

**Trade-offs accepted:**
- k6 runs as a single process on the load generator machine. At 500 VUs, k6 itself consumes significant CPU and memory on the same developer laptop as the stack, which distorts latency measurements upward.
- k6 does not produce graphical reports without Grafana Cloud or a local InfluxDB setup.

---

## uv (package manager)

**Decision:** Use uv over pip, Poetry, or pipenv.

**Rationale:**
- uv resolves and installs the full dependency graph in under 1 second (vs. 30–60s for pip).
- uv manages the Python version automatically via `.python-version` — no `pyenv` or `asdf` needed.
- `uv sync --frozen` in the Dockerfile produces a deterministic, reproducible build from `uv.lock`.
- `uv run <script>` executes scripts in the project venv without `source .venv/bin/activate`.

**Trade-offs accepted:**
- uv is relatively new (2024). Some CI environments may not have it pre-installed, requiring the bootstrap `curl` step.
- `uv.lock` format is not compatible with `pip freeze` or `requirements.txt` tooling.

---

## Docker Compose (container orchestration)

**Decision:** Use Docker Compose over Kubernetes, Nomad, or bare Docker commands.

**Rationale:**
- Docker Compose is the right tool for a single-host multi-container development and demo environment. The entire stack starts with one command.
- Kubernetes would be the right choice for production multi-host deployments, but the operational overhead (cluster setup, YAML manifests, ingress controllers, persistent volume claims) is not justified for a hackathon demo.
- `depends_on` with `condition: service_healthy` ensures the correct startup order (PostgreSQL and Redis must be healthy before app containers start) without custom shell polling.

**Trade-offs accepted:**
- Docker Compose v2 does not support automatic failover or pod rescheduling. If a container crashes, it must be manually restarted (or configured with `restart: always`).
- The current compose file does not set `restart: unless-stopped` — intentional for development (you want containers to stay stopped after a crash so you can inspect logs).
