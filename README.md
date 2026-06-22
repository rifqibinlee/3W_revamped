# 3W Revamped

Production rebuild of the 3W network-analytics platform (GIS site planning, AI agent querying, congestion analytics, messaging/IAM, BI dashboards).

This is a from-scratch rewrite of the original 3W app. See [docs/adr/0001-architecture.md](docs/adr/0001-architecture.md) for the full architecture decision and rationale, and [docs/REBUILD_PLAN.md](docs/REBUILD_PLAN.md) for the phased rollout.

## Stack

- **Backend:** FastAPI (Python), modular routers per domain
- **Analytics:** DuckDB over local Parquet files (replaces AWS Athena-on-CSV)
- **Transactional/RAG data:** PostgreSQL 16 + pgvector
- **Object storage (local):** MinIO (S3-compatible), swapped for real S3 in the AWS phase
- **Frontend:** React + Vite + MapLibre GL
- **BI:** Metabase (kept from the original stack)
- **AI agent:** LangGraph + LiteLLM (Claude) + Ollama (local models)
- **Spatial:** GeoServer (WMS/WFS), Shapely, OSMnx

## Status

Phase 0 — foundations. See [docs/REBUILD_PLAN.md](docs/REBUILD_PLAN.md) for current phase and what's next.

## Local development

```bash
docker compose -f infra/docker-compose.yml up -d
```

See [backend/README.md](backend/README.md) and [frontend/README.md](frontend/README.md) once scaffolded.
