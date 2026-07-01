# ADR 0001: 3W Rebuild Architecture

## Status
Accepted — 2026-06-22

## Context

The original 3W app (Flask monolith, ~4,400 LOC across `app.py`/`agent.py`) has:
- Analytics queries running through AWS Athena against raw CSV files in S3 — slow (full scans, no indexes, no columnar format) and the suspected root cause of the app's loading-speed complaints.
- Hardcoded credentials, an SQL-injection-prone query pattern in the agent tools, zero tests, zero CI, zero docs.
- No clear module boundaries — auth, chat, GIS, agent tools, and pricing logic all live in one file.
- A dual map-rendering stack (Leaflet + Cesium) increasing frontend complexity for no clear benefit.

Constraints for the rebuild:
- Must run fully locally first (no AWS dependency) and become AWS-deployable only in the final phase.
- Target production host is a single EC2 instance with **40GB total disk**, shared across the DB, object storage, analytics data, Ollama models, GeoServer, and Metabase.

## Decision

- **Analytics engine:** Replace Athena-on-CSV with **DuckDB reading local Parquet files**. DuckDB is embedded (no separate server process), reads columnar Parquet directly, and easily handles the existing data volumes (10K-100K rows/query) in milliseconds. This is the lightest-footprint option for the 40GB disk budget — no daemon, minimal RAM overhead, unlike ClickHouse.
- **Backend framework:** **FastAPI**, split into per-domain routers (`auth`, `annotations`, `chat`, `agent`, `siteplanning`, `ingestion`, `analytics`). Pydantic models enforce request/response validation at every boundary, which also closes the SQL-injection gap (parameterized queries only, no string interpolation into SQL).
- **Frontend:** **React + Vite + MapLibre GL**, replacing the Leaflet/Cesium split with a single map library that handles both 2D and 3D via terrain. Built as a static bundle, served by the backend or nginx — runs fine 24/7 on a single EC2 instance.
- **Transactional data:** **PostgreSQL 16** for users, auth, chat, annotations, pricing, reviews.
- **RAG knowledge base:** **PostgreSQL FTS** (`to_tsvector` / `plainto_tsquery` with GIN index) — replaces pgvector + Ollama embeddings. No extension required, no model weight to host, simpler schema. Ingests PDFs and Excel workbooks from S3.
- **Object storage:** **MinIO** locally (S3-compatible API), **AWS S3** in production — same boto3 SDK calls, no code changes. Processed Parquet is written directly to S3 (not downloaded to EC2 disk) via DuckDB httpfs.
- **AI agent:** **Claude only** (`langchain-anthropic`) via LangGraph `create_react_agent`. Ollama removed — eliminates ~4GB model weight from the EC2 disk budget. `ANTHROPIC_API_KEY` is a hard requirement; the app raises `RuntimeError` at startup if absent.
- **Spatial pipelines:** CCTV planning (Shapely) and Genset routing (OSMnx) logic retained, re-platformed as testable standalone services.

## Consequences

- Local dev requires no AWS account or credentials until the final deployment phase (set `USE_REAL_S3=false`, use MinIO).
- In production (`USE_REAL_S3=true`), processed Parquet files live entirely in S3 — EC2 disk only holds the OS, app, PostgreSQL data, and in-flight temp copies of raw files (~100-167MB each, deleted after each stage). Weekly network data growth does not accumulate on disk.
- DuckDB's single-process model means the analytics layer cannot be horizontally scaled independently of the backend process — acceptable at current data volumes; revisit (e.g. move to ClickHouse or Athena-on-Parquet) only if query volume or data size grows significantly beyond what fits in the instance.
- Dropping pgvector removes the need for the PostgreSQL `vector` extension and Ollama embedding models. The tradeoff is keyword-match precision vs. semantic similarity — acceptable for the current telecom-document corpus where exact terminology (PRB, CAPEX, zoom_sector_id) is more important than conceptual proximity.
- Dropping Cesium removes any 3D-specific features that depended on it; MapLibre's terrain support is the replacement and needs verification against actual use cases during the frontend rebuild phase.

## Addendum — 2026-06-22: ETL pipeline scope correction

Reviewing the original 10 ETL scripts (`scripts/`) and sample raw data (`dataset_example/`) revealed the ingestion layer is substantially heavier than initially scoped:

- Raw inputs are weekly XLSB/XLSX/CSV exports from two vendor datasets (Huawei "xC", ZTE "xD"), 95-167MB per file, forming a DAG: `{xC, xD} raw → sector calculations → congestion analysis → {CD combined result, pre-CAPEX → CAPEX upgrades, forecast results}`, plus an independent coverage-holes DBSCAN branch fed by MR/Ookla signal data.
- The original scripts do correctness-heavy work in Python loops (per-sector 12-case CAPEX upgrade solver, per-sector linear regression for forecasting, chunked pandas aggregation) — this, not just "Athena on CSV," is a second source of slowness.
- Raw sample files exceed GitHub's 100MB push limit and must never be committed; `dataset_example/` is git-ignored. Only Parquet outputs and code are version-controlled.

A second review (after the `scripts/` legacy folder was added, since renamed `scripts_example/`) found one more gap: `reference xC & xD cell_Dec25.xlsb` — the master cell-hardware reference (XTXR/MIMO config, bandwidth → avail_prb) — was re-parsed independently by **four** legacy scripts (`xC Huawei Dataset.py`, `xD (ZTE Dataset).py`, `Pre-Capacity-CAPEX-Upgrades.py`, `Capacity-CAPEX-Upgrades.py`), each reading the same raw file from `s3://.../site_coverage_params/referenceData/` from scratch. The new DAG pulls this out into its own `cell_reference` stage, parsed once, with those four stages depending on it instead.

Decisions arising from this:
- Rewrite vectorizable steps (congestion filtering, sector aggregation, forecast regression via window functions) as **DuckDB SQL** rather than pandas loops — this is the real performance lever, independent of swapping Athena for DuckDB.
- Treat raw vendor files as **ephemeral**: stream from MinIO/S3, transform, write Parquet, delete local temp copies. The 40GB EC2 disk budget cannot hold raw + intermediate + Parquet simultaneously at current file sizes.
- Model the ETL as an explicit ordered DAG (not a flat script folder) so dependencies (e.g. CAPEX-Upgrades requires Pre-CAPEX-Upgrades requires Congestion-Analysis requires {xC, xD} sector calculations) are enforced, not implicit in run order.

## Addendum — 2026-07-01: S3-native Parquet, Claude-only, FTS RAG

Three decisions revised from the original plan after facing real production constraints:

### 1. Processed Parquet lives in S3, not on EC2 disk

**Problem:** ETL processes ~100-167MB raw XLSB files weekly. Even with ephemeral raw-file staging, the processed Parquet outputs (congestion, forecast, capex, etc.) were accumulating on the EC2 instance — growing ~several hundred MB per week indefinitely. The 40GB disk budget has no room for this.

**Decision:** `app/ingestion/parquet_store.py` routes all ETL output paths. When `USE_REAL_S3=true`:
- Every `COPY … TO` in every ETL stage writes to `s3://jejak-mappro-demo/3W-data/processed/<filename>.parquet` via DuckDB httpfs.
- All `read_parquet(…)` calls in analytics read directly from S3 via the same httpfs extension — no download step.
- EC2 disk only ever holds in-flight temp copies of individual raw files, deleted after each stage.

On EC2 with an IAM role that has `s3:GetObject` + `s3:PutObject` on the bucket, no explicit credentials are needed: `SET s3_use_credential_chain=true` in DuckDB, and boto3's default credential resolution chain handles the same for raw-file staging.

### 2. Ollama removed; Claude is the only LLM provider

**Problem:** The Ollama fallback required hosting `qwen2.5:7b` (~4GB) and `nomic-embed-text` (~270MB) on the same EC2 instance as the rest of the stack. Practically this forced an oversized instance just to run tests, and the embedding model was coupled to pgvector.

**Decision:** Claude (`claude-sonnet-4-6`) is the only provider. `ANTHROPIC_API_KEY` is a hard requirement — the app raises a clear `RuntimeError` at boot if absent. No model weights on disk, no Ollama process, no GPU requirement.

### 3. pgvector + Ollama embeddings replaced by PostgreSQL FTS

**Problem:** pgvector required: (a) the `vector` extension on every PostgreSQL instance, (b) Ollama running to generate embeddings at ingest time, and (c) a `vector(768)` column with a NOT NULL constraint that made the schema fragile. Removing Ollama made this untenable.

**Decision:** `knowledge_chunks` stores plain text. Retrieval uses PostgreSQL built-in `to_tsvector('english', content) @@ plainto_tsquery('english', :q)` with `ts_rank` ordering, accelerated by a GIN index (migration `0005`). An `ILIKE` fallback handles short or single-term queries. No extension, no model, no embedding column. The corpus is telecom-specific enough that exact terminology matching (PRB, CAPEX, zoom_sector_id, band names) outperforms semantic search in practice.

## Rollout

See [docs/REBUILD_PLAN.md](../REBUILD_PLAN.md) for the phased plan (Phase 0 foundations → Phase 6 AWS readiness).
