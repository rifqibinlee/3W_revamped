"""Agent tools: every function the AI can call.

Tools cover:
- Congestion & forecast status (from DuckDB Parquet analytics)
- CAPEX pricing (from PostgreSQL)
- Arbitrary read-only DuckDB SQL for power-user queries
- Knowledge base search (PDF/Excel training data via PostgreSQL FTS)
- Site coordinates and coverage hole lookups
"""

import duckdb
from langchain_core.tools import tool

from app.analytics import service as analytics_service
from app.analytics.db import get_connection
from app.core.db import SessionLocal
from app.ingestion.parquet_store import parquet_uri
from app.pricing import service as pricing_service
from app.rag import service as rag_service


# ── Congestion & forecast ──────────────────────────────────────────────────────

@tool
def get_current_congestion_status(zoom_sector_id: str) -> dict:
    """Look up the current (latest week) congestion status for a specific
    sector by its zoom_sector_id (e.g. 'SITE001_Macro_1')."""
    row = analytics_service.sector_current_status(zoom_sector_id)
    return row or {"error": f"No congestion data found for sector {zoom_sector_id}"}


@tool
def get_forecast_status(zoom_sector_id: str, year: int, week: int) -> dict:
    """Look up the forecasted congestion status for a sector at a future
    year/week (planning horizon: weeks 13, 26, 39, 52)."""
    row = analytics_service.sector_forecast_status(zoom_sector_id, year, week)
    return row or {"error": f"No forecast found for sector {zoom_sector_id} at {year} week {week}"}


@tool
def list_congested_sectors(region: str = "") -> list[dict]:
    """Return all sectors currently flagged as congested. Optionally filter
    by region name (case-insensitive substring match). Returns up to 50 rows."""
    parquet = parquet_uri("congestion_analysis.parquet")
    con = get_connection()
    try:
        if region:
            return con.execute(
                f"SELECT zoom_sector_id, site_id, region, congested FROM read_parquet('{parquet}') "
                "WHERE congested = true AND lower(region) LIKE lower(?) LIMIT 50",
                [f"%{region}%"],
            ).fetchdf().to_dict(orient="records")
        return con.execute(
            f"SELECT zoom_sector_id, site_id, region, congested FROM read_parquet('{parquet}') "
            "WHERE congested = true LIMIT 50"
        ).fetchdf().to_dict(orient="records")
    finally:
        con.close()


# ── Site info ──────────────────────────────────────────────────────────────────

@tool
def get_site_info(site_id: str) -> dict:
    """Return coordinates, region, and cluster for a site_id. Also returns
    the number of sectors and whether any are currently congested."""
    parquet_sites = parquet_uri("site_coordinates.parquet")
    parquet_cong = parquet_uri("congestion_analysis.parquet")
    con = get_connection()
    try:
        site = con.execute(
            f"SELECT * FROM read_parquet('{parquet_sites}') WHERE site_id = ? LIMIT 1",
            [site_id],
        ).fetchdf()
        if site.empty:
            return {"error": f"Site {site_id} not found"}
        row = site.iloc[0].to_dict()
        cong = con.execute(
            f"SELECT COUNT(*) as sectors, SUM(CASE WHEN congested THEN 1 ELSE 0 END) as congested_sectors "
            f"FROM read_parquet('{parquet_cong}') WHERE site_id = ?",
            [site_id],
        ).fetchdf().iloc[0].to_dict()
        return {**row, **cong}
    finally:
        con.close()


# ── Analytics direct query ─────────────────────────────────────────────────────

_BLOCKED_SQL_KEYWORDS = frozenset({
    "INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER",
    "COPY", "ATTACH", "DETACH", "PRAGMA", "EXPORT", "IMPORT",
    "INSTALL", "LOAD",
})


@tool
def query_analytics(sql: str) -> list[dict]:
    """Run a read-only SQL query directly against the DuckDB analytics
    warehouse. Use parquet_uri() paths as shown in the tool descriptions
    for read_parquet(). Returns up to 100 rows. SELECT only."""
    sql_upper = sql.upper()
    if any(kw in sql_upper for kw in _BLOCKED_SQL_KEYWORDS):
        return [{"error": "Only SELECT queries are allowed. Blocked keywords detected."}]
    con = get_connection()
    try:
        df = con.execute(sql).fetchdf()
        return df.head(100).to_dict(orient="records")
    except Exception as exc:
        return [{"error": str(exc)}]
    finally:
        con.close()


# ── Coverage holes ─────────────────────────────────────────────────────────────

@tool
def get_coverage_holes(region: str = "") -> list[dict]:
    """Return DBSCAN-identified coverage holes (weak-signal clusters from MR
    and Ookla data). Optionally filter by region. Returns up to 30 clusters."""
    parquet = parquet_uri("coverage_holes.parquet")
    con = get_connection()
    try:
        if region:
            return con.execute(
                f"SELECT * FROM read_parquet('{parquet}') WHERE lower(region) LIKE lower(?) LIMIT 30",
                [f"%{region}%"],
            ).fetchdf().to_dict(orient="records")
        return con.execute(
            f"SELECT * FROM read_parquet('{parquet}') LIMIT 30"
        ).fetchdf().to_dict(orient="records")
    except Exception as exc:
        return [{"error": str(exc)}]
    finally:
        con.close()


# ── CAPEX pricing ──────────────────────────────────────────────────────────────

@tool
def get_capex_pricing() -> dict:
    """Returns the current CAPEX equipment/services pricing table (EQ/ES
    categories) used to cost out network upgrade recommendations."""
    db = SessionLocal()
    try:
        return pricing_service.get_pricing(db)
    finally:
        db.close()


# ── Knowledge base ─────────────────────────────────────────────────────────────

@tool
def search_knowledge_base(query: str) -> list[dict]:
    """Search the internal knowledge base (ingested PDFs and Excel training
    data from S3) for information relevant to the query. Returns the top 5
    matching text excerpts with their source document and page number."""
    db = SessionLocal()
    try:
        chunks = rag_service.search(db, query, top_k=5)
        return [
            {"source": c.source, "page": c.page, "excerpt": c.content[:400]}
            for c in chunks
        ]
    finally:
        db.close()


ALL_TOOLS = [
    get_current_congestion_status,
    get_forecast_status,
    list_congested_sectors,
    get_site_info,
    query_analytics,
    get_coverage_holes,
    get_capex_pricing,
    search_knowledge_base,
]
