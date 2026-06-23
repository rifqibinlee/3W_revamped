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
- [x] **Phase 2 — Core domain services**
  - [x] Alembic-managed Postgres schema — `0001` users/login_history, `0002` annotations/annotation_comments, `0003` chat tables + deferred FK, `0004` capex_pricing_items/reviews/review_comments/review_reactions — all verified by generating real DDL in offline mode
  - [x] Auth/IAM: registration, login, JWT (access + refresh), bcrypt, RBAC (Admin/Planner/Staff), login history — `app/auth/`
  - [x] Annotations/Tasks (map annotations double as a lightweight PM tool) — `app/annotations/`:
    - [x] Unassigned annotation = plain note; assigning it to someone converts it into a task
    - [x] Task fields: assignee, due date, status (todo/in_progress/pending_review/done/rejected)
    - [x] Gantt endpoint: simple per-assignee timeline (created_at -> due_date) per task, no dependency graph — `GET /annotations/gantt/rows`; chart rendering itself is Phase 5
    - [x] Review workflow: assignee submits for review -> `pending_review`; assigner approves (-> `done`) or rejects (-> back to `in_progress` with a reason). Assignee can never self-approve; only the task's creator or an admin can review — enforced and tested
    - [x] Per-assignment chat room: creating/assigning a task auto-creates a direct conversation between creator and assignee via `chat.service.get_or_create_direct_conversation`
  - [x] Chat — `app/chat/`: DMs (idempotent get-or-create), group conversations, send/list messages gated by participant membership, per-user unread counts
  - [x] CAPEX pricing admin — `app/pricing/`: editable EQ/ES table backing `capex_solver.py`, falls back to its `DEFAULT_PRICING` when empty, admin-only writes
  - [x] Reviews/feedback — `app/reviews/`: rating/category/comment, toggleable like/dislike reactions
  - [x] Split-screen current-vs-forecast API — `app/analytics/`: `GET /analytics/current-status` and `GET /analytics/forecast-status?year=&week=`, both reading Phase 1's Parquet outputs directly and joining site coordinates. Map UI itself (synced Leaflet/MapLibre panes) is Phase 5.
  - [x] 92/92 tests passing, ruff clean across all of Phase 2
- [x] **Phase 3 — Spatial & planning pipelines** — `app/siteplanning/`
  - [x] CCTV site planning (`cctv.py`): ported from `cctv2_pipeline.py` near-verbatim (already QGIS-free pure Python); `POST /siteplanning/cctv/run` accepts GeoJSON + camera/offset specs as JSON, core pipeline still takes file paths internally
  - [x] Genset/substation routing (`genset.py`): ported from `genset_pipeline.py`, road-network distance via OSMnx filtered to 2km, refactored with an injectable `graph_provider` so tests use a synthetic graph instead of the live OSM API; `POST /siteplanning/genset/route`
  - [x] 14 new tests, 106/106 total passing, ruff clean
- [x] **Phase 4 — AI agent & RAG**
  - [x] LLM provider switch (`app/agent/llm.py`): Claude primary (`ChatAnthropic`), Ollama automatic local-dev fallback when `ANTHROPIC_API_KEY` is unset — both implement LangChain's standard interface so the rest of the agent code is provider-agnostic. Embeddings always stay on Ollama (no Anthropic embeddings API)
  - [x] Agent (`app/agent/`): LangGraph ReAct loop (`langchain.agents.create_agent`) with 3 tools rewired against Phase 1/2 data (current congestion, forecast status, CAPEX pricing) instead of the legacy Athena-backed versions — `POST /agent/chat`
  - [x] RAG (`app/rag/`): PDF chunk/embed/store (ports `s3_ingest.py` minus the S3-specific download), cosine-similarity search computed in Python rather than pgvector's native operator (simpler, equally testable at this corpus scale) — `POST /rag/ingest` (FastAPI `BackgroundTasks`, not a separate task queue), `POST /rag/search`
  - [x] Migration `0005`: pgvector extension + `knowledge_chunks` table, verified by generating real DDL in offline mode
  - [x] 15 new tests, 121/121 total passing, ruff clean
- [ ] **Phase 5 — Frontend rebuild:** React + Vite + Tailwind v4 + MapLibre GL, Metabase embedding
  - [x] Design system locked in: glassmorphic panels on a deep indigo-blue background, live canvas particle stream (blue/yellow, ~2200 particles, glow), Space Grotesk + Plus Jakarta Sans (deliberately not the default Inter/Roboto look)
  - [x] Foundation: Vite scaffold, Tailwind v4 theme tokens, `ParticleBackground`, `GlassPanel`, `AppShell` (nav), API client + auth context wired to the real backend
  - [x] Login page — wired to `POST /auth/login`
  - [x] Dashboard page — wired to `GET /analytics/current-status` + `GET /annotations/gantt/rows` (real data, not mock), full legacy "RAN Forecast" tab ported (filter bar, stat tiles, sector metrics/congested/forecast tables)
  - [x] Map page — MapLibre GL, split-screen current-vs-forecast (synced panes), icon-based draw tool (point/line/polygon/buffer) creating a brand-new note or project per shape, rich site-detail popup (KPIs + forecast + CAPEX upgrade), viewport-scoped + network-wide stats panels (`GET /analytics/map-stats`, `GET /analytics/overview-stats`)
  - [x] Notes page — list + description + map centered on the note's annotation
  - [x] Projects page — list + kanban (todo/in progress/pending review/done) + auto-generated Gantt strip + discussion thread; tasks support multiple assignees
  - [x] Chat page — conversation list (`GET /chat/conversations`, new) + thread view + new-DM composer
  - [x] CAPEX pricing admin page — two-tier (admin sees/edits exact price, staff sees range only)
  - [x] Agent page — chat UI against the stateless `POST /agent/chat` (LLM provider reachability is an environment concern, not a page bug)
  - [ ] Reviews page, RAG search UI, Metabase embedding
  - [x] Frontend typecheck/lint clean throughout, vitest clean, 170/170 backend tests passing
- [ ] **Phase 6 — AWS readiness:** Terraform (S3, RDS, ECS/Fargate or App Runner), secrets migration, CI/CD deploy pipeline

See [docs/adr/0001-architecture.md](adr/0001-architecture.md) for the architecture rationale behind these choices.
