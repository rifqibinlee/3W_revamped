# Rebuild Plan

Module-by-module phased rebuild of 3W. Each phase should be reviewed before moving to the next.

- [x] **Phase 0 — Foundations:** repo structure, ADR, CI scaffolding, local docker-compose (Postgres, MinIO, Ollama)
- [ ] **Phase 1 — Data layer migration:** ETL DAG ported from `scripts/` (legacy reference, see `backend/app/ingestion/dag.py`) to DuckDB SQL
  - [x] DAG defined (`backend/app/ingestion/dag.py`) — explicit dependency order for all 10 legacy stages
  - [x] `storage.py` — ephemeral raw-file staging from MinIO/S3 (never persisted beyond one transform)
  - [x] Stage 1/10 implemented: `site_coordinates`
  - [ ] `site_coverage_params`, `xc_huawei`, `xd_zte`, `congestion_analysis`, `cd_combined_result`, `pre_capex_upgrades`, `capex_upgrades`, `forecast_results`, `coverage_holes`
  - [ ] Alembic-managed Postgres schema (replacing `app_database_setup.py`)
- [ ] **Phase 2 — Core domain services:** Auth/IAM, Annotations, Chat, CAPEX pricing, Reviews
- [ ] **Phase 3 — Spatial & planning pipelines:** CCTV site planning, Genset/substation routing
- [ ] **Phase 4 — AI agent & RAG:** LangGraph agent tools against DuckDB, PDF ingestion pipeline with background worker
- [ ] **Phase 5 — Frontend rebuild:** React + Vite + MapLibre GL, Metabase embedding
- [ ] **Phase 6 — AWS readiness:** Terraform (S3, RDS, ECS/Fargate or App Runner), secrets migration, CI/CD deploy pipeline

See [docs/adr/0001-architecture.md](adr/0001-architecture.md) for the architecture rationale behind these choices.
