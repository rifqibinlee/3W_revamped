"""Agent tools: plain Python functions wrapped with LangChain's `@tool`
decorator, each opening its own DB connection/session — same pattern as
the rest of this codebase (ETL stages open their own DuckDB connection,
nothing holds a request-scoped session across an LLM round trip).

Ported from the legacy agent.py's congestion/forecast/pricing tools,
rewired against this rebuild's Phase 1 DuckDB Parquet outputs and Phase 2
pricing service instead of Athena.
"""

from langchain_core.tools import tool

from app.analytics import service as analytics_service
from app.core.db import SessionLocal
from app.pricing import service as pricing_service


@tool
def get_current_congestion_status(zoom_sector_id: str) -> dict:
    """Look up the current (latest week) congestion status for a specific
    sector by its zoom_sector_id (e.g. 'SITE001_Macro_1')."""
    rows = analytics_service.current_status()
    for row in rows:
        if row.get("zoom_sector_id") == zoom_sector_id:
            return row
    return {"error": f"No congestion data found for sector {zoom_sector_id}"}


@tool
def get_forecast_status(zoom_sector_id: str, year: int, week: int) -> dict:
    """Look up the forecasted congestion status for a sector at a future
    year/week (the planning UI offers quarter weeks 13, 26, 39, 52)."""
    rows = analytics_service.forecast_status(year, week)
    for row in rows:
        if row.get("zoom_sector_id") == zoom_sector_id:
            return row
    return {"error": f"No forecast found for sector {zoom_sector_id} at {year} week {week}"}


@tool
def get_capex_pricing() -> dict:
    """Returns the current CAPEX equipment/services pricing table (EQ/ES
    categories) used to cost out network upgrade recommendations."""
    db = SessionLocal()
    try:
        return pricing_service.get_pricing(db)
    finally:
        db.close()


ALL_TOOLS = [get_current_congestion_status, get_forecast_status, get_capex_pricing]
