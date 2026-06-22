"""CAPEX upgrades: runs the 12-case solver (`app.ingestion.capex_solver`)
for every congested sector in a pre_capex_upgrades file.

Ports `scripts_example/Capacity-CAPEX-Upgrades.py`. Data loading and the
per-sector band aggregation are DuckDB SQL; the upgrade-path search itself
stays a per-sector Python loop calling the pure `calculate_upgrade_path`
function — that step is an iterative early-exit search over two 14-step
sequences, not something that reduces to a SQL aggregation.

aggregated_bands per sector (band, f1f2f3 layer, summed avail_prb, first
xtxr) comes straight from cell_reference grouped by
(zoom_sector_id, band, f1f2f3) — cell_reference already carries
everything the legacy script's `ref_dict` rebuilt from scratch by
re-parsing the raw reference file yet again.
"""

from pathlib import Path

import pandas as pd

from app.analytics.db import get_connection
from app.core.config import settings
from app.ingestion.capex_solver import BW_MAP_GLOBAL, calculate_upgrade_path

OUTPUT_TABLE = "capex_upgrades"

LAYER_BAND_KEYS = ("F1_L18", "F1_L21", "F1_L26", "F1_L9", "F2_L18", "F2_L21", "F2_L26", "F2_L9")


def run(pre_capex_path: str, congestion_path: str, cell_reference_path: str, pricing: dict) -> Path | None:
    con = get_connection()
    try:
        return _run(con, pre_capex_path, congestion_path, cell_reference_path, pricing)
    finally:
        con.close()


def _run(con, pre_capex_path: str, congestion_path: str, cell_reference_path: str, pricing: dict) -> Path | None:
    context_df = con.execute(f"""
        SELECT
            pc.zoom_sector_id, pc.dataset_type, pc.year, pc.week,
            pc.sum_existing_prb, pc.sum_rb_used, pc.additional_rb,
            ca.area_target, ca.ibc_macro, ca.bau_nic, ca.operator, ca.region
        FROM read_parquet('{pre_capex_path}') pc
        INNER JOIN (
            SELECT DISTINCT zoom_sector_id, year, week, area_target, ibc_macro, bau_nic, operator, region
            FROM read_parquet('{congestion_path}')
        ) ca ON pc.zoom_sector_id = ca.zoom_sector_id AND pc.year = ca.year AND pc.week = ca.week
    """).fetchdf()

    if context_df.empty:
        return None

    band_rows = con.execute(f"""
        SELECT zoom_sector_id, band, f1f2f3 AS layer, sum(avail_prb) AS avail_prb, first(xtxr) AS current_xtxr
        FROM read_parquet('{cell_reference_path}')
        GROUP BY zoom_sector_id, band, f1f2f3
    """).fetchall()

    bands_by_sector: dict[str, list[dict]] = {}
    for zoom_sector_id, band, layer, avail_prb, current_xtxr in band_rows:
        bands_by_sector.setdefault(zoom_sector_id, []).append(
            {"band": band, "layer": layer, "avail_prb": avail_prb, "current_xtxr": current_xtxr}
        )

    results: list[dict] = []
    for ctx in context_df.to_dict("records"):
        sector_id = ctx["zoom_sector_id"]
        ds_type = ctx["dataset_type"]

        sector_bands = bands_by_sector.get(sector_id, [])
        aggregated_bands = []
        for b in sector_bands:
            avail_prb = b["avail_prb"]
            if not avail_prb:
                lookup = BW_MAP_GLOBAL.get((b["layer"], b["band"], ds_type), 0)
                avail_prb = lookup * 5.0
            aggregated_bands.append({
                "band": b["band"], "layer": b["layer"],
                "avail_prb": avail_prb, "current_xtxr": b["current_xtxr"],
            })

        curr_map, sugg_map, case_label, total_capex, eq_capex, es_capex, projected_prb = calculate_upgrade_path(
            aggregated_bands,
            ctx["area_target"], ctx["ibc_macro"], ctx["bau_nic"], ctx["operator"],
            ds_type, pricing,
            ctx["sum_rb_used"], ctx["sum_existing_prb"], ctx["additional_rb"], ctx["region"],
        )

        result = {
            "zoom_sector_id": sector_id,
            "data_year": ctx["year"],
            "data_week": ctx["week"],
            "area_target": ctx["area_target"],
            "dataset_type": ds_type,
            "suggested_upgrade_case": case_label,
            "estimated_total_capex_rm": float(total_capex),
            "eq_capex_rm": float(eq_capex),
            "es_capex_rm": float(es_capex),
            "projected_prb_pct": float(projected_prb),
        }
        for k in LAYER_BAND_KEYS:
            short = k.lower()
            result[f"current_{short}"] = curr_map.get(k, "0")
            result[f"suggested_{short}"] = sugg_map.get(k, "0")
        results.append(result)

    if not results:
        return None

    df = pd.DataFrame(results)
    output_path = Path(settings.parquet_dir) / f"{OUTPUT_TABLE}_{Path(pre_capex_path).stem}.parquet"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    con.register("capex_results_df", df)
    con.execute(f"COPY capex_results_df TO '{output_path}' (FORMAT PARQUET, COMPRESSION SNAPPY)")
    return output_path
