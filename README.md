# 3W Revamped

Production rebuild of the 3W network-analytics platform (GIS site planning, AI agent querying, congestion analytics, messaging/IAM, BI dashboards).

This is a from-scratch rewrite of the original 3W app. See [docs/adr/0001-architecture.md](docs/adr/0001-architecture.md) for the full architecture decision and rationale, and [docs/REBUILD_PLAN.md](docs/REBUILD_PLAN.md) for the phased rollout.

## Stack

- **Backend:** FastAPI (Python 3.10+), modular routers per domain
- **Analytics:** DuckDB over local Parquet files (replaces AWS Athena-on-CSV)
- **Transactional/RAG data:** PostgreSQL 16 + pgvector
- **Object storage (local):** MinIO (S3-compatible), swapped for real S3 in the AWS phase
- **Frontend:** React 19 + Vite + Tailwind v4 + MapLibre GL
- **BI:** Metabase (kept from the original stack; not yet wired up)
- **AI agent:** LangGraph + LangChain, Claude primary / Ollama automatic local-dev fallback
- **Spatial:** GeoServer (WMS/WFS), Shapely, OSMnx

## Status

Phase 5 (frontend) is mostly complete — see [docs/REBUILD_PLAN.md](docs/REBUILD_PLAN.md) for the
detailed phase-by-phase checklist and what's left (Reviews page, RAG search UI, Metabase embedding,
then Phase 6 AWS readiness).

## Local development

1. Start infra (Postgres, MinIO):

   ```bash
   docker compose -f infra/docker-compose.yml up -d postgres minio
   ```

2. Backend — copy `backend/.env.example` to `backend/.env` and fill in real values, then:

   ```bash
   cd backend
   pip install -e ".[dev]"          # or: pip install -e . -r requirements-lock.txt
   alembic upgrade head
   uvicorn app.main:app --reload    # http://localhost:8000, docs at /docs
   ```

3. Frontend:

   ```bash
   cd frontend
   npm install
   npm run dev                      # http://localhost:5173 (or next free port)
   ```

Run tests with `pytest -q` (backend) and `npx vitest run` (frontend) — both also run in CI on every
push/PR that touches their respective directory (`.github/workflows/`).
