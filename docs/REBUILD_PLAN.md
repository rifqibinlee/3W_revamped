# Rebuild Plan

Module-by-module phased rebuild of 3W. Each phase should be reviewed before moving to the next.

- [x] **Phase 0 — Foundations:** repo structure, ADR, CI scaffolding, local docker-compose (Postgres, MinIO, Ollama)
- [ ] **Phase 1 — Data layer migration:** convert existing S3 CSVs to Parquet, load into DuckDB, Alembic-managed Postgres schema
- [ ] **Phase 2 — Core domain services:** Auth/IAM, Annotations, Chat, CAPEX pricing, Reviews
- [ ] **Phase 3 — Spatial & planning pipelines:** CCTV site planning, Genset/substation routing
- [ ] **Phase 4 — AI agent & RAG:** LangGraph agent tools against DuckDB, PDF ingestion pipeline with background worker
- [ ] **Phase 5 — Frontend rebuild:** React + Vite + MapLibre GL, Metabase embedding
- [ ] **Phase 6 — AWS readiness:** Terraform (S3, RDS, ECS/Fargate or App Runner), secrets migration, CI/CD deploy pipeline

See [docs/adr/0001-architecture.md](adr/0001-architecture.md) for the architecture rationale behind these choices.
