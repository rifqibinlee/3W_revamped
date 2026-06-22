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
- **Transactional + RAG data:** Kept as **PostgreSQL 16 + pgvector** — this part of the original system was already sound.
- **Object storage:** **MinIO** locally (S3-compatible API), swapped for real AWS S3 in the deployment phase with no code changes (same boto3 SDK calls).
- **BI dashboards:** **Metabase retained**, re-pointed at the new DuckDB/Postgres data layer instead of Athena.
- **AI agent:** LangGraph + LiteLLM(Claude)/Ollama retained, but tool implementations rewritten against the new DuckDB analytics layer with parameterized queries.
- **Spatial pipelines:** CCTV planning (Shapely) and Genset routing (OSMnx) logic retained, re-platformed as testable standalone services.

## Consequences

- Local dev requires no AWS account or credentials until the final deployment phase.
- Parquet conversion is a one-time migration step for existing CSV data sitting in S3.
- DuckDB's single-process model means the analytics layer cannot be horizontally scaled independently of the backend process — acceptable at current data volumes; revisit (e.g. move to ClickHouse or Athena-on-Parquet) only if query volume or data size grows significantly beyond what fits in the 40GB instance.
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

## Rollout

See [docs/REBUILD_PLAN.md](../REBUILD_PLAN.md) for the phased plan (Phase 0 foundations → Phase 6 AWS readiness).
