"""Admin-facing raw-data management: upload categorized source files —
mirroring the categories the Phase 1 ETL stages actually consume (site
and cell config exports, the xC/xD cell reference workbook, and the
weekly Network Data PRB utilization exports) — and trigger the ETL
pipeline against whatever's currently uploaded.

Storage is the filesystem under settings.raw_data_dir, organized the
same way dataset_example/ already is: flat for non-weekly categories,
one subfolder per ISO week for "network_data". There's no legacy S3
directory taxonomy to carry over — the legacy app queried Athena tables
directly with year/week as columns, not S3 prefixes, per the
architecture research that preceded this module.
"""

import re
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

from app.core.config import settings
from app.ingestion.capex_solver import DEFAULT_PRICING
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

CATEGORIES: dict[str, dict] = {
    "site_data": {"label": "Site & Cell Exports", "weekly": False},
    "cell_reference": {"label": "Cell Reference (xC & xD)", "weekly": False},
    "network_data": {"label": "Network Data", "weekly": True},
}

WEEK_PATTERN = re.compile(r"^\d{4}-W\d{2}$")
PREVIEW_LIMIT = 200
SUPPORTED_SUFFIXES = (".csv", ".xlsx", ".xls", ".xlsb")


class UnknownCategoryError(Exception):
    pass


class InvalidWeekError(Exception):
    pass


class UnsupportedFileTypeError(Exception):
    pass


def _category_dir(category: str, week: str | None) -> Path:
    if category not in CATEGORIES:
        raise UnknownCategoryError(category)
    root = Path(settings.raw_data_dir) / category
    if CATEGORIES[category]["weekly"]:
        if not week or not WEEK_PATTERN.match(week):
            raise InvalidWeekError("week must be in 'YYYY-Www' format, e.g. 2026-W13")
        return root / week
    return root


def list_categories() -> list[dict]:
    out = []
    for key, meta in CATEGORIES.items():
        root = Path(settings.raw_data_dir) / key
        if not root.exists():
            count = 0
        elif meta["weekly"]:
            count = sum(1 for p in root.glob("*/*") if p.is_file())
        else:
            count = sum(1 for p in root.glob("*") if p.is_file())
        out.append({"key": key, "label": meta["label"], "weekly": meta["weekly"], "file_count": count})
    return out


def list_weeks(category: str) -> list[str]:
    if category not in CATEGORIES or not CATEGORIES[category]["weekly"]:
        return []
    root = Path(settings.raw_data_dir) / category
    if not root.exists():
        return []
    return sorted((p.name for p in root.iterdir() if p.is_dir()), reverse=True)


def list_files(category: str, week: str | None = None) -> list[dict]:
    folder = _category_dir(category, week)
    if not folder.exists():
        return []
    files = []
    for p in sorted(folder.iterdir()):
        if not p.is_file():
            continue
        stat = p.stat()
        files.append({
            "filename": p.name,
            "size_bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
        })
    return files


def save_file(category: str, week: str | None, filename: str, content: bytes) -> Path:
    folder = _category_dir(category, week)
    folder.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename).name  # strip any path components — never trust the client's filename
    if Path(safe_name).suffix.lower() not in SUPPORTED_SUFFIXES:
        raise UnsupportedFileTypeError(safe_name)
    path = folder / safe_name
    path.write_bytes(content)
    return path


def delete_file(category: str, week: str | None, filename: str) -> None:
    folder = _category_dir(category, week)
    path = folder / Path(filename).name
    path.unlink(missing_ok=True)


def preview_file(category: str, week: str | None, filename: str) -> dict:
    folder = _category_dir(category, week)
    path = folder / Path(filename).name
    if not path.exists():
        raise FileNotFoundError(filename)

    suffix = path.suffix.lower()
    if suffix == ".csv":
        con = duckdb.connect()
        try:
            df = con.execute(
                f"SELECT * FROM read_csv(?, ignore_errors=true, sample_size=-1) LIMIT {PREVIEW_LIMIT + 1}",
                [str(path)],
            ).fetchdf()
        finally:
            con.close()
    elif suffix in (".xlsx", ".xls"):
        df = pd.read_excel(path, nrows=PREVIEW_LIMIT + 1)
    elif suffix == ".xlsb":
        df = pd.read_excel(path, engine="pyxlsb", nrows=PREVIEW_LIMIT + 1)
    else:
        raise UnsupportedFileTypeError(suffix)

    truncated = len(df) > PREVIEW_LIMIT
    df = df.head(PREVIEW_LIMIT)
    df = df.astype(object).where(pd.notnull(df), None)
    return {
        "columns": [str(c) for c in df.columns],
        "rows": df.values.tolist(),
        "truncated": truncated,
    }


def run_pipeline() -> dict:
    """Runs the ETL stages against whatever's currently uploaded. Site
    config and cell reference are category-wide (every file in the
    category feeds the same stage call); Network Data is processed once
    per uploaded week, matching how the stages are actually shaped
    (xc_huawei/pre_capex_upgrades take one raw file at a time)."""
    site_files = [str(p) for p in (Path(settings.raw_data_dir) / "site_data").glob("*") if p.is_file()]
    cell_ref_files = [str(p) for p in (Path(settings.raw_data_dir) / "cell_reference").glob("*") if p.is_file()]
    network_root = Path(settings.raw_data_dir) / "network_data"
    weekly_files = [str(p) for p in network_root.glob("*/*") if p.is_file()] if network_root.exists() else []

    result: dict[str, list[str]] = {"stages_run": [], "stages_skipped": []}

    if site_files:
        site_coordinates.run(site_files)
        site_coverage_params.run(site_files)
        result["stages_run"] += ["site_coordinates", "site_coverage_params"]
    else:
        result["stages_skipped"].append("site_coordinates/site_coverage_params (no site_data files)")

    if not cell_ref_files:
        result["stages_skipped"].append("cell_reference and everything downstream (no cell_reference files)")
        return result
    cell_reference_path = cell_reference.run(cell_ref_files)
    result["stages_run"].append("cell_reference")

    if not weekly_files:
        result["stages_skipped"].append(
            "xc_huawei/congestion_analysis/forecast_results/capex_upgrades (no network_data files)"
        )
        return result

    xc_paths = [str(xc_huawei.run(f, str(cell_reference_path))) for f in weekly_files]
    result["stages_run"].append(f"xc_huawei ({len(xc_paths)} weekly file(s))")

    congestion_path = congestion_analysis.run(xc_paths, [])
    result["stages_run"].append("congestion_analysis")

    cd_combined_result.run(xc_paths, [], str(congestion_path))
    result["stages_run"].append("cd_combined_result")

    pre_capex_paths = [
        out for f in weekly_files
        if (out := pre_capex_upgrades.run(f, str(cell_reference_path), str(congestion_path), "xC")) is not None
    ]
    if pre_capex_paths:
        for p in pre_capex_paths:
            capex_upgrades.run(str(p), str(congestion_path), str(cell_reference_path), DEFAULT_PRICING)
        result["stages_run"].append(f"pre_capex_upgrades+capex_upgrades ({len(pre_capex_paths)} week(s))")

    forecast_results.run(xc_paths, [])
    result["stages_run"].append("forecast_results")

    return result
