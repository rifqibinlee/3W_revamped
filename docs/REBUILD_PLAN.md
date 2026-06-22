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
- [ ] **Phase 2 — Core domain services**
  - [x] Alembic-managed Postgres schema — `0001` (users, login_history), `0002` (annotations, annotation_comments), both verified by generating real DDL in offline mode
  - [x] Auth/IAM: registration, login, JWT (access + refresh), bcrypt, RBAC (Admin/Planner/Staff), login history — `app/auth/`
  - [x] Annotations/Tasks (map annotations double as a lightweight PM tool) — `app/annotations/`:
    - [x] Unassigned annotation = plain note; assigning it to someone converts it into a task
    - [x] Task fields: assignee, due date, status (todo/in_progress/pending_review/done/rejected)
    - [x] Gantt endpoint: simple per-assignee timeline (created_at -> due_date) per task, no dependency graph — `GET /annotations/gantt/rows`; chart rendering itself is Phase 5
    - [x] Review workflow: assignee submits for review -> `pending_review`; assigner approves (-> `done`) or rejects (-> back to `in_progress` with a reason). Assignee can never self-approve; only the task's creator or an admin can review — enforced and tested
    - [x] Per-assignment chat room: creating/assigning a task auto-creates a direct conversation between creator and assignee via `chat.service.get_or_create_direct_conversation`
  - [x] Chat — `app/chat/`: DMs (idempotent get-or-create), group conversations, send/list messages gated by participant membership, per-user unread counts. Migration `0003` adds the FK from `annotations.conversation_id` deferred since `0002`
  - [ ] CAPEX pricing admin: CRUD over the EQ/ES pricing table that `capex_solver.py` already consumes
  - [ ] Reviews/feedback module (ports reviews/comments/reactions from the legacy app — distinct from task review above)
  - [ ] Split-screen current-vs-forecast API: two read endpoints over data Phase 1 already produces — current status from `congestion_analysis`, forecast status from `forecast_results` filtered by year + quarter-week (13/26/39/52), matching the legacy `/api/forecast_data` contract. Map UI itself (synced Leaflet/MapLibre panes) is Phase 5.
- [ ] **Phase 3 — Spatial & planning pipelines:** CCTV site planning, Genset/substation routing
- [ ] **Phase 4 — AI agent & RAG:** LangGraph agent tools against DuckDB, PDF ingestion pipeline with background worker
- [ ] **Phase 5 — Frontend rebuild:** React + Vite + MapLibre GL, Metabase embedding
- [ ] **Phase 6 — AWS readiness:** Terraform (S3, RDS, ECS/Fargate or App Runner), secrets migration, CI/CD deploy pipeline

See [docs/adr/0001-architecture.md](adr/0001-architecture.md) for the architecture rationale behind these choices.
