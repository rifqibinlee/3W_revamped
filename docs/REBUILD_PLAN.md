# Rebuild Plan

Module-by-module phased rebuild of 3W. Each phase should be reviewed before moving to the next.

- [x] **Phase 0 — Foundations:** repo structure, ADR, CI scaffolding, local docker-compose (Postgres, MinIO, Ollama)
- [x] **Phase 1 — Data layer migration:** ETL DAG ported from `scripts_example/` (legacy reference) to DuckDB SQL
  - [x] DAG defined (`backend/app/ingestion/dag.py`) — explicit dependency order for all 11 stages (10 legacy scripts + `cell_reference`, extracted from 4 scripts that were each re-parsing the same raw reference file independently)
  - [x] `storage.py` — ephemeral raw-file staging from MinIO/S3 (never persisted beyond one transform)
  - [x] All 11/11 stages implemented: `site_coordinates`, `site_coverage_params`, `cell_reference`, `xc_huawei`, `xd_zte`, `congestion_analysis`, `cd_combined_result`, `pre_capex_upgrades`, `capex_upgrades`, `forecast_results`, `coverage_holes`
  - [x] **S3-native Parquet output** (`app/ingestion/parquet_store.py`): when `USE_REAL_S3=true`, all ETL stages write processed Parquet directly back to `s3://jejak-mappro-demo/3W-data/processed/` via DuckDB httpfs (`COPY … TO 's3://…'`). EC2 disk is only used for in-flight temp copies of raw files. DuckDB reads analytics Parquet directly from S3 via `read_parquet('s3://…')` — no processed files ever accumulate on disk. On EC2 with an IAM role attached, no explicit AWS credentials are required (DuckDB `SET s3_use_credential_chain=true`).
  - [x] **Two-pipeline modes in `datamgmt/service.py`**: `_run_pipeline_local()` reads from `RAW_DATA_DIR` on disk (dev/test); `_run_pipeline_s3()` lists raw files from the three S3 prefixes, stages each network file once for xc_huawei (Pass 1), computes congestion, then re-stages each file for pre_capex_upgrades (Pass 2) — so EC2 never holds more than one ~100MB weekly file at a time.
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
  - [x] LLM provider: **Claude only** (`ChatAnthropic` via `langchain-anthropic`). Ollama removed entirely — eliminates the ~4GB model weight from the EC2 disk budget and the "Ollama allocation" crashes. `ANTHROPIC_API_KEY` is required; the app raises a clear `RuntimeError` at startup if absent.
  - [x] Agent (`app/agent/`): LangGraph ReAct loop (`create_react_agent` from `langgraph.prebuilt`) with **8 tools** against Phase 1/2 data — `POST /agent/chat`:
    - `get_current_congestion_status` — latest-week KPIs for a specific sector
    - `get_forecast_status` — forecast congestion at a year/week horizon
    - `list_congested_sectors` — all congested sectors, optional region filter
    - `get_site_info` — coordinates, region, cluster, sector count for a site
    - `query_analytics` — read-only DuckDB SQL with keyword injection guard (`SELECT` only; `INSERT/UPDATE/DELETE/DROP/CREATE/ALTER/COPY/ATTACH/PRAGMA/INSTALL/LOAD` blocked)
    - `get_coverage_holes` — DBSCAN anomaly clusters, optional region filter
    - `get_capex_pricing` — current EQ/ES pricing table from PostgreSQL
    - `search_knowledge_base` — PostgreSQL FTS over ingested PDFs and Excel training data
  - [x] RAG (`app/rag/`): **pgvector and Ollama embeddings removed**. Storage is plain PostgreSQL text (`knowledge_chunks` table), retrieval uses `to_tsvector` / `plainto_tsquery` FTS with `ts_rank` ordering, falling back to `ILIKE` for short/single-term queries. Supports PDF (pypdf) and Excel (pandas) ingestion. S3 sync endpoint (`POST /rag/sync-s3`) ingests new files from `s3_train_pdf_prefix` / `s3_train_excel_prefix`, skipping already-ingested sources.
  - [x] Migration `0005`: **rewritten** — plain `knowledge_chunks` table with a GIN FTS index (`to_tsvector('english', content)`). No pgvector extension, no embedding column, no `Vector(768) NOT NULL` constraint that would break every INSERT.
  - [x] 15 new tests, 121/121 total passing, ruff clean
- [ ] **Phase 5 — Frontend rebuild:** React + Vite + Tailwind v4 + MapLibre GL, Metabase embedding
  - [x] Design system locked in: glassmorphic panels (shadow depth + inset highlight + top shine line) on an
    animated CSS/SVG gradient background (blue/yellow drifting blobs + grain texture — replaced an earlier
    canvas particle-stream prototype that wasn't reliably rendering), Space Grotesk + Plus Jakarta Sans
  - [x] Foundation: Vite scaffold, Tailwind v4 theme tokens, `AnimatedBackground`, `GlassPanel`, `AppShell` (nav), API client + auth context wired to the real backend
  - [x] Login page — wired to `POST /auth/login`
  - [x] Dashboard page — wired to `GET /analytics/current-status` + `GET /annotations/gantt/rows` (real data, not mock); full legacy "RAN Forecast" tab ported as three sub-tabs (sector metrics/forecasts/congested), each with real server-side pagination (`{rows, total}`) instead of a silently-truncated first page; live per-site forecast graph (`ForecastChart`, plain SVG — actual line + dashed projection + 95% confidence band) wired to `GET /analytics/site-forecast/{site_id}`, the same live-linear-regression method as the legacy `/plot` route
  - [x] Map page — MapLibre GL, split-screen current-vs-forecast (synced panes), icon-based draw tool (point/line/polygon/buffer) creating a brand-new note or project per shape, rich site-detail popup (KPIs + forecast + CAPEX upgrade), viewport-scoped + network-wide stats panels (`GET /analytics/map-stats`, `GET /analytics/overview-stats`)
  - [x] Notes page — list + description + map centered on the note's annotation
  - [x] Projects page — list + kanban (todo/in progress/pending review/done) + auto-generated Gantt strip + discussion thread; tasks support multiple assignees
  - [x] Chat page — conversation list (`GET /chat/conversations`, new) + thread view + new-DM composer
  - [x] CAPEX pricing admin page — two-tier (admin sees/edits exact price, staff sees range only)
  - [x] Agent page — chat UI against the stateless `POST /agent/chat` (LLM provider reachability is an environment concern, not a page bug)
  - [x] Data management page (admin-only) — upload raw source files by category (site/cell exports, cell reference, weekly Network Data), spreadsheet-style preview, trigger the ETL pipeline from the UI; ETL run for real against `dataset_example/` for the first time in this environment (30,750 sites, 947 congested sectors across 3 of 4 weeks, RM 415M in CAPEX recommendations — week 48 still fails on an unresolved real data issue)
  - [ ] Reviews page, RAG search UI, Metabase embedding
  - [x] Frontend typecheck/lint clean throughout, vitest clean, 198/198 backend tests passing (1 known pre-existing flaky timestamp-ordering test, passes in isolation)
- [ ] **Phase 6 — AWS readiness**
  - [x] S3-native ETL: processed Parquet written to and read from `s3://jejak-mappro-demo/3W-data/processed/` — EC2 never accumulates data files. Set `USE_REAL_S3=true` to activate.
  - [x] S3 training-data sync: `POST /rag/sync-s3` ingests PDFs/Excel from `3W-data/train-ai-data/` into the PostgreSQL knowledge base
  - [x] IAM-role credential chain: when `AWS_ACCESS_KEY`/`AWS_SECRET_KEY` are blank, both boto3 and DuckDB httpfs pick up credentials from EC2 instance metadata automatically
  - [x] S3 bucket layout documented in `.env.example` and `config.py`
  - [ ] Terraform: VPC, EC2 (t3.medium recommended for testing — ~$30/mo), RDS PostgreSQL, IAM role with S3 read/write on `jejak-mappro-demo`
  - [ ] Secrets: `POSTGRES_DSN`, `JWT_SECRET`, `ANTHROPIC_API_KEY` via AWS Secrets Manager or SSM Parameter Store (not baked into AMI)
  - [ ] CI/CD: GitHub Actions → build Docker image → push to ECR → `ssh` deploy to EC2 (or swap to ECS if horizontal scale is needed later)
  - [ ] CORS_ORIGINS: set to the actual frontend domain in production (not the Vite dev-server range)

See [docs/adr/0001-architecture.md](adr/0001-architecture.md) for the architecture rationale behind these choices.
