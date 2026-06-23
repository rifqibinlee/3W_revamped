"""Runner: reproduce the one-time manual real-data ETL validation run.

Per docs/REBUILD_PLAN.md Phase 1: the `UME_RRP_4G_AUTOMATION BOT_WK4PK_WEEK*_2025.xlsb`
files in `dataset_example/Network Data/` were originally assumed to be xD/ZTE
weekly KPI exports but turned out to be site-config exports instead. They're
used here as extra site-coordinate/coverage-param inputs; xd_zte has no real
matching data in this dataset and is skipped entirely (xd_paths = [] throughout).
coverage_holes is also skipped — no real MR/Ookla data exists in this dataset.

Run from the `backend/` directory so `settings.parquet_dir` (./data/parquet)
resolves to `backend/data/parquet`:

    cd backend
    ./.venv/Scripts/python scripts/run_real_etl.py
"""

import sys
import time
from pathlib import Path

# Make `app` importable when run as a plain script from backend/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.ingestion.capex_solver import DEFAULT_PRICING
from app.ingestion.dag import topological_order
from app.ingestion.stages import (
    capex_upgrades,
    cd_combined_result,
    cell_reference,
    congestion_analysis,
    forecast_results,
    pre_capex_upgrades,
    site_coordinates,
    site_coverage_params,
    xc_huawei,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = REPO_ROOT / "dataset_example"
NETWORK_DATA_DIR = DATASET_DIR / "Network Data"


def p(*parts: str) -> str:
    return str(Path(*parts))


SITE_FILES = [
    p(DATASET_DIR, "dnb_4g_20260119.xlsx"),
    p(DATASET_DIR, "dnb_5g_20260119.csv"),
    p(DATASET_DIR, "femto_20260119.xlsx"),
    p(DATASET_DIR, "mocn_2g_20260119.xlsx"),
    p(DATASET_DIR, "mocn_4g_20260119.xlsx"),
    p(DATASET_DIR, "nfcp_3g_20260119.xlsx"),
    p(DATASET_DIR, "site_info_2g_20260119.xlsx"),
    p(DATASET_DIR, "site_info_4g_20260119.csv"),
    p(DATASET_DIR, "t3e_2g_20260119.xlsx"),
    p(DATASET_DIR, "t3e_3g_20260119.xlsx"),
    p(NETWORK_DATA_DIR, "UME_RRP_4G_AUTOMATION BOT_WK4PK_WEEK47_2025.xlsb"),
    p(NETWORK_DATA_DIR, "UME_RRP_4G_AUTOMATION BOT_WK4PK_WEEK48_2025.xlsb"),
    p(NETWORK_DATA_DIR, "UME_RRP_4G_AUTOMATION BOT_WK4PK_WEEK49_2025.xlsb"),
    p(NETWORK_DATA_DIR, "UME_RRP_4G_AUTOMATION BOT_WK4PK_WEEK50_2025.xlsb"),
]

CELL_REFERENCE_FILES = [
    p(DATASET_DIR, "reference xC & xD cell_Dec25.xlsb"),
]

XC_WEEKLY_FILES_ALL = [
    p(NETWORK_DATA_DIR, "2025 W48 4G PRB Util - 24-30 Nov.xlsb"),
    p(NETWORK_DATA_DIR, "2025 W49 4G PRB Util - 01-07 Dec.xlsb"),
    p(NETWORK_DATA_DIR, "2025 W50 4G PRB Util - 08-14 Dec (Huawei Ericsson).xlsb"),
    p(NETWORK_DATA_DIR, "2025 W52 4G PRB Util - 22-28 Dec.xlsb"),
]


def _readable(path: str) -> bool:
    """Skip files OneDrive hasn't hydrated locally yet / reports a sync
    error on (cloud-only placeholder with FILE_ATTRIBUTE_REPARSE_POINT that
    raises PermissionError on open) rather than crashing the whole run."""
    try:
        with open(path, "rb") as f:
            f.read(4)
        return True
    except OSError:
        return False


XC_WEEKLY_FILES = [f for f in XC_WEEKLY_FILES_ALL if _readable(f)]
SKIPPED_XC_FILES = [f for f in XC_WEEKLY_FILES_ALL if f not in XC_WEEKLY_FILES]

XD_PATHS: list[str] = []  # xd_zte skipped — no real matching data in this dataset


def section(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def main() -> None:
    t0 = time.time()

    # Sanity check: confirm the DAG's declared ordering agrees with the
    # order this script calls stages in. Doesn't auto-wire file paths.
    order = [s.name for s in topological_order() if s.implemented]
    print("DAG topological order (implemented stages):", order)

    print(f"settings.parquet_dir = {settings.parquet_dir!r} -> {Path(settings.parquet_dir).resolve()}")
    if SKIPPED_XC_FILES:
        print("WARNING: skipping unreadable (OneDrive not hydrated / sync error) xC weekly files:")
        for f in SKIPPED_XC_FILES:
            print("  -", f)

    results: dict[str, object] = {}

    section("1/9 site_coordinates")
    site_coordinates_path = site_coordinates.run(SITE_FILES)
    results["site_coordinates"] = site_coordinates_path
    print("->", site_coordinates_path)

    section("2/9 site_coverage_params")
    site_coverage_params_path = site_coverage_params.run(SITE_FILES)
    results["site_coverage_params"] = site_coverage_params_path
    print("->", site_coverage_params_path)

    section("3/9 cell_reference")
    cell_reference_path = cell_reference.run(CELL_REFERENCE_FILES)
    results["cell_reference"] = cell_reference_path
    print("->", cell_reference_path)

    section("4/9 xc_huawei (one call per weekly file)")
    xc_paths: list[str] = []
    for f in XC_WEEKLY_FILES:
        out = xc_huawei.run(f, str(cell_reference_path))
        print("  ", f, "->", out)
        xc_paths.append(str(out))
    results["xc_huawei"] = xc_paths

    section("5/9 congestion_analysis")
    congestion_path = congestion_analysis.run(xc_paths, XD_PATHS)
    results["congestion_analysis"] = congestion_path
    print("->", congestion_path)

    section("6/9 cd_combined_result")
    cd_outputs = cd_combined_result.run(xc_paths, XD_PATHS, str(congestion_path))
    results["cd_combined_result"] = cd_outputs
    for k, v in cd_outputs.items():
        print(f"  {k} -> {v}")

    section("7/9 pre_capex_upgrades (one call per raw xC weekly file)")
    pre_capex_paths: list[str] = []
    for f in XC_WEEKLY_FILES:
        out = pre_capex_upgrades.run(f, str(cell_reference_path), str(congestion_path), dataset_type="xC")
        print("  ", f, "->", out)
        if out is not None:
            pre_capex_paths.append(str(out))
    results["pre_capex_upgrades"] = pre_capex_paths

    section("8/9 capex_upgrades (one call per pre_capex_upgrades output)")
    pricing = DEFAULT_PRICING
    capex_paths: list[str] = []
    for f in pre_capex_paths:
        out = capex_upgrades.run(f, str(congestion_path), str(cell_reference_path), pricing)
        print("  ", f, "->", out)
        if out is not None:
            capex_paths.append(str(out))
    results["capex_upgrades"] = capex_paths

    section("9/9 forecast_results")
    forecast_path = forecast_results.run(xc_paths, XD_PATHS)
    results["forecast_results"] = forecast_path
    print("->", forecast_path)

    section("SKIPPED")
    print("xd_zte: skipped, no real matching data in this dataset")
    print("coverage_holes: skipped, no real MR/Ookla data in this dataset")

    section("Row counts")
    import duckdb

    def count(path) -> int | None:
        if path is None:
            return None
        try:
            return duckdb.sql(f"SELECT count(*) FROM read_parquet('{path}')").fetchone()[0]
        except Exception as e:  # noqa: BLE001
            return f"ERROR: {e}"

    for name in ("site_coordinates", "site_coverage_params", "cell_reference", "congestion_analysis", "forecast_results"):
        print(f"{name}: {count(results[name])} rows")
    for i, xc in enumerate(xc_paths):
        print(f"xc_huawei[{i}] ({Path(xc).name}): {count(xc)} rows")
    for i, cp in enumerate(capex_paths):
        print(f"capex_upgrades[{i}] ({Path(cp).name}): {count(cp)} rows")

    print(f"\nTotal elapsed: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
