# MLH PE Hackathon — Flask + Peewee + PostgreSQL + Redis

A production-engineering hackathon project covering **all 4 quests at Gold tier**: Scalability, Reliability, Incident Response, and Documentation.

The stack runs locally as a single Flask process for development and scales to a 3-replica Nginx-load-balanced cluster with Redis caching, Prometheus/Grafana monitoring, and automated alerting via Docker Compose.

**Stack:** Python 3.13 · Flask 3.1 · Peewee ORM · PostgreSQL 16 · Redis 7 · Nginx · Gunicorn (gevent) · Prometheus · Grafana · Alertmanager · uv

**Quality:** 47 tests · 88% coverage · CI/CD via GitHub Actions · Structured JSON logging

---

## Quick Start (local development)

### Prerequisites

| Tool | Install |
|---|---|
| **uv** | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| **PostgreSQL 16** | `brew install postgresql@16` or Docker (see below) |
| **Python 3.13** | managed automatically by uv |

### 1 — Clone and install

```bash
git clone <repo-url>
cd PE-Hackathon
uv sync                  # creates .venv, installs all deps
```

### 2 — Start PostgreSQL

**Option A — Docker (recommended, no local Postgres needed):**
```bash
docker run -d \
  --name hackathon-pg \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=hackathon_db \
  -p 5432:5432 \
  postgres:16-alpine
```

**Option B — local Postgres:**
```bash
createdb hackathon_db
```

### 3 — Configure environment

```bash
cp .env.example .env
# .env is pre-configured for the defaults above — edit only if your credentials differ
```

### 4 — Create tables and seed data

```bash
uv run python seed.py
# → Tables created.
# → Seeded 100 products.
```

### 5 — Run the server

```bash
uv run run.py
```

### 6 — Verify

```bash
curl http://127.0.0.1:5000/health
# → {"status":"ok"}

curl http://127.0.0.1:5000/products | python3 -m json.tool | head -20
```

> **macOS note:** Port 5000 is claimed by AirPlay on IPv6. Always use `127.0.0.1:5000`, not `localhost:5000`.

---

## Quick Start (full Docker Compose stack)

Runs Nginx + 3 Flask replicas + PostgreSQL + Redis + Prometheus + Grafana + Alertmanager — no local Python needed.

```bash
# Build images and start all services (10 containers)
docker compose up --build -d

# Wait for health checks to pass, then verify
curl http://127.0.0.1:80/health
# → {"status":"ok"}

curl http://127.0.0.1:80/health/ready
# → {"status":"ok","checks":{"database":"ok","cache":"ok"}}

curl http://127.0.0.1:80/products | python3 -m json.tool | head -10
```

**Monitoring dashboards:**

| Service | URL | Credentials |
|---|---|---|
| Grafana | http://127.0.0.1:3001 | admin / admin |
| Prometheus | http://127.0.0.1:9090 | — |
| Alertmanager | http://127.0.0.1:9093 | — |

To stop:
```bash
docker compose down          # keeps database volume
docker compose down -v       # also deletes database volume
```

---

## Project Structure

```
PE-Hackathon/
├── app/
│   ├── __init__.py          # App factory + JSON error handlers + health endpoints
│   ├── cache.py             # Redis cache wrapper (get/set/delete/stats)
│   ├── database.py          # Peewee DatabaseProxy + connection lifecycle hooks
│   ├── logging_config.py    # Structured JSON logging setup
│   ├── metrics.py           # Prometheus metrics + /metrics endpoint
│   ├── models/
│   │   ├── __init__.py      # Import all models here
│   │   └── product.py       # Product model (unique name constraint)
│   └── routes/
│       ├── __init__.py      # register_routes() — add blueprints here
│       ├── products.py      # GET/POST /products, GET /products/<id> + validation
│       └── cache_stats.py   # GET /cache/stats
├── tests/
│   ├── conftest.py          # Fixtures: in-memory SQLite, Flask test client
│   ├── test_api.py          # Integration tests for all endpoints
│   ├── test_cache.py        # Cache module unit tests
│   └── test_models.py       # Product model CRUD tests
├── .github/
│   └── workflows/
│       └── ci.yml           # GitHub Actions: pytest + coverage on every push/PR
├── monitoring/
│   ├── prometheus.yml       # Prometheus scrape config
│   ├── alert_rules.yml      # ServiceDown, HighErrorRate, HighLatency alerts
│   ├── alertmanager.yml     # Alert routing to Discord
│   └── grafana/
│       ├── provisioning/    # Auto-configured datasource + dashboard provider
│       └── dashboards/
│           └── app-dashboard.json  # Four Golden Signals dashboard
├── docs/
│   ├── architecture.md      # System diagrams (Mermaid)
│   ├── api.md               # Full API reference
│   ├── configuration.md     # All environment variables
│   ├── deploy_guide.md      # Docker Compose deployment + scaling
│   ├── troubleshooting.md   # Common issues and fixes
│   ├── runbooks.md          # Operational playbooks
│   ├── decision_log.md      # Why we chose each technology
│   ├── capacity_plan.md     # Load test results + scaling projections
│   ├── bottleneck_report.md # Bronze → Silver → Gold optimization story
│   └── failure_modes.md     # What happens when things break
├── loadtest/
│   ├── bronze_test.js       # k6: 50 VUs × 30s
│   ├── silver_test.js       # k6: 200 VUs × 60s
│   ├── gold_test.js         # k6: 500 VUs × 120s
│   └── results/             # Captured test outputs
├── docker-compose.yml       # Full stack: 10 services (app × 3 + infra + monitoring)
├── docker-entrypoint.sh     # Container startup: wait → seed → gunicorn (gevent)
├── Dockerfile               # App image build
├── nginx.conf               # Round-robin upstream config
├── pyproject.toml           # Dependencies + pytest config (uv)
├── run.py                   # Local dev entry point: uv run run.py
└── seed.py                  # Idempotent: creates tables + inserts 100 products
```

---

## Adding a Model

1. Create `app/models/your_model.py`:

```python
from peewee import CharField, DecimalField, IntegerField
from app.database import BaseModel

class YourModel(BaseModel):
    name = CharField()
    value = DecimalField(decimal_places=2)
```

2. Import it in `app/models/__init__.py`:

```python
from app.models.your_model import YourModel
```

3. Create the table (run once, e.g., in `seed.py`):

```python
from app.database import db
db.create_tables([YourModel], safe=True)
```

## Adding Routes

1. Create `app/routes/your_bp.py` with a Flask Blueprint.
2. Register it in `app/routes/__init__.py`:

```python
def register_routes(app):
    from app.routes.your_bp import your_bp
    app.register_blueprint(your_bp)
```

## Running Tests

```bash
# Run all tests with coverage
uv run pytest -v

# Run with detailed coverage report
uv run pytest --cov=app --cov-report=term-missing

# Run a specific test file
uv run pytest tests/test_api.py -v
```

CI runs these automatically on every push/PR via GitHub Actions. The build fails if coverage drops below 70%.

## Running Load Tests

```bash
# Install k6 (macOS)
brew install k6

# Bronze: 50 VUs × 30s against local dev server
uv run run.py &
k6 run loadtest/bronze_test.js

# Silver/Gold: against Docker Compose stack
docker compose up --build -d
k6 run loadtest/silver_test.js   # 200 VUs × 60s
k6 run loadtest/gold_test.js     # 500 VUs × 120s
```

## Useful uv Commands

| Command | What it does |
|---|---|
| `uv sync` | Install all dependencies |
| `uv run <script>` | Run a script in the project venv |
| `uv add <package>` | Add a new dependency |
| `uv remove <package>` | Remove a dependency |

## Documentation

| Doc | Description |
|---|---|
| [Architecture](docs/architecture.md) | System diagrams and component overview |
| [API Reference](docs/api.md) | All endpoints with request/response examples |
| [Configuration](docs/configuration.md) | All environment variables and defaults |
| [Deploy Guide](docs/deploy_guide.md) | Docker Compose deployment and scaling |
| [Troubleshooting](docs/troubleshooting.md) | Common issues and fixes |
| [Runbooks](docs/runbooks.md) | Operational playbooks |
| [Decision Log](docs/decision_log.md) | Why we chose each technology |
| [Capacity Plan](docs/capacity_plan.md) | Load test results and scaling projections |
| [Bottleneck Report](docs/bottleneck_report.md) | Optimization story across all tiers |
| [Failure Modes](docs/failure_modes.md) | What happens when components break |
