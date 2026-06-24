# 3W Revamped — Backend

FastAPI + SQLAlchemy 2.0 + DuckDB. See the [repo root README](../README.md) for the full-stack
overview and [docs/REBUILD_PLAN.md](../docs/REBUILD_PLAN.md) for what's built.

## Setup

```bash
cp .env.example .env   # fill in real values — see comments in the file
pip install -e ".[dev]"          # loose constraints, for development
# or, for a reproducible install:
pip install -e . -r requirements-lock.txt

alembic upgrade head
uvicorn app.main:app --reload    # http://localhost:8000, interactive docs at /docs
```

Requires Postgres 16 + pgvector and MinIO running (`docker compose -f ../infra/docker-compose.yml up -d postgres minio`).

## Scripts

| Command | Does |
|---|---|
| `pytest -q` | Run the test suite (SQLite in-memory for unit tests, real Postgres for a few integration ones) |
| `ruff check .` | Lint |
| `mypy app` | Type-check (not yet a CI gate — see Known gaps below) |
| `alembic revision --autogenerate -m "..."` | New migration |
| `python scripts/run_real_etl.py` | Re-run the full ETL pipeline against `dataset_example/` |

## Structure

One module per domain under `app/`, each typically with `models.py` / `schemas.py` / `service.py` /
`router.py`:

- `auth/` — registration, JWT login (access + refresh), bcrypt, RBAC, login history
- `annotations/` — map annotations; unassigned = note, assigned = project with tasks (multi-assignee,
  review workflow) and an auto-created chat room
- `chat/` — DMs, group conversations, unread counts
- `pricing/` — two-tier CAPEX pricing (admin sees exact price, everyone else sees a range)
- `reviews/` — ratings/comments/reactions
- `analytics/` — DuckDB-over-Parquet read layer: current/forecast status, map stats, per-site
  forecast (live linear regression + confidence band), the legacy "RAN Forecast" tables
- `agent/` — LangGraph ReAct agent; Claude primary, Ollama automatic local-dev fallback
- `rag/` — PDF ingestion + cosine-similarity search for the agent's knowledge base
- `siteplanning/` — CCTV site planning, genset/substation routing
- `datamgmt/` — admin raw-file upload + ETL pipeline trigger
- `ingestion/` — the Phase 1 ETL stages (DuckDB SQL ports of the legacy `scripts_example/` scripts)
- `core/` — settings, DB session

## Known gaps

- `mypy app` isn't a CI gate yet — most of what it currently reports is missing third-party type
  stubs (pandas, scipy, sklearn, etc.), not real bugs. Worth revisiting once stub packages are added,
  rather than as a blocking gate today.
- `requirements-lock.txt` is a plain `pip freeze` snapshot, not a resolver-generated lockfile (no
  `pip-tools`/`uv` in the toolchain yet) — regenerate it manually after intentionally upgrading a
  dependency (see the comment at the top of the file).
- ETL week 48 (`dataset_example/Network Data`) fails on a real data issue not yet root-caused.
