# Rebuild Plan

Module-by-module phased rebuild of 3W. Each phase should be reviewed before moving to the next.

- [x] **Phase 0 — Foundations:** repo structure, ADR, CI scaffolding, local docker-compose (Postgres, MinIO, Ollama)
- [x] **Phase 1 — Data layer migration:** ETL DAG ported from `scripts_example/` (legacy reference) to DuckDB SQL
  - [x] DAG defined (`backend/app/ingestion/dag.py`) — explicit dependency order for all 11 stages (10 legacy scripts + `cell_reference`, extracted from 4 scripts that were each re-parsing the same raw reference file independently)
  - [x] `storage.py` — ephemeral raw-file staging from MinIO/S3 (never persisted beyond one transform)
  - [x] All 11/11 stages implemented: `site_coordinates`, `site_coverage_params`, `cell_reference`, `xc_huawei`, `xd_zte`, `congestion_analysis`, `cd_combined_result`, `pre_capex_upgrades`, `capex_upgrades`, `forecast_results`, `coverage_holes`
  - [x] 41/41 tests passing, ruff clean
  - [x] Real-data validation: ran `site_coordinates` → `site_coverage_params` → `cell_reference` → `xc_huawei` (4 real weekly files) → `congestion_analysis` → `cd_combined_result` → `pre_capex_upgrades` → `capex_upgrades` → `forecast_results` end-to-end against the actual files in `dataset_example/`. Found and fixed 8 real bugs the synthetic fixtures couldn't catch (column-detection gaps, DuckDB CSV type-inference sampling, pyarrow mixed-type conversion failures, Windows temp-file handle leaks, output filename collisions silently overwriting prior weeks). Final real numbers: 20,637 sites, 421,511 coverage params, 342,512 cell references, ~18K sectors/week, 527/17,556 congested in one week (~3%), 945,360 forecast rows across 18,180 sectors.
  - [ ] `xd_zte` and `coverage_holes` validated only against synthetic fixtures — no matching real sample data exists in `dataset_example/` (files assumed to be xD weekly KPI exports turned out to be site config exports; no MR/Ookla coverage data was provided)
  - [ ] Alembic-managed Postgres schema (replacing `app_database_setup.py`) — moved to Phase 2 since it's transactional, not analytics
  - [ ] Not yet built: a real orchestrator/scheduled job that runs this automatically (each stage was run manually, one at a time, for this validation)
- [ ] **Phase 2 — Core domain services:** Auth/IAM, Annotations, Chat, CAPEX pricing, Reviews
- [ ] **Phase 3 — Spatial & planning pipelines:** CCTV site planning, Genset/substation routing
- [ ] **Phase 4 — AI agent & RAG:** LangGraph agent tools against DuckDB, PDF ingestion pipeline with background worker
- [ ] **Phase 5 — Frontend rebuild:** React + Vite + MapLibre GL, Metabase embedding
- [ ] **Phase 6 — AWS readiness:** Terraform (S3, RDS, ECS/Fargate or App Runner), secrets migration, CI/CD deploy pipeline

See [docs/adr/0001-architecture.md](adr/0001-architecture.md) for the architecture rationale behind these choices.
