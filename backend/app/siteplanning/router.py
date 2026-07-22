import base64
import csv
import io
import json
import logging
import re
import tempfile
import time
from pathlib import Path

import duckdb
import pandas as pd
from fastapi import APIRouter, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse

from app.analytics.db import get_connection
from app.ingestion import parquet_store
from app.siteplanning.cctv import run_cctv_pipeline
from app.siteplanning.genset import find_all_power_sources, route_substations
from app.siteplanning.schemas import CctvRunRequest, GensetRouteRequest, GensetSingleRequest

log = logging.getLogger(__name__)

router = APIRouter(prefix="/siteplanning", tags=["siteplanning"])


@router.post("/cctv/run")
def cctv_run(payload: CctvRunRequest) -> dict:
    """run_cctv_pipeline takes file paths (matching the legacy script);
    this writes the JSON request body to temp files so the core pipeline
    function doesn't need an HTTP-specific code path."""
    tmp_paths: list[str] = []
    try:
        building_path = _write_temp_json(payload.building)
        parking_path = _write_temp_json(payload.parking)
        poles_path = _write_temp_json(payload.poles)
        camera_path = _write_temp_csv(
            [c.model_dump() for c in payload.cameras], ("camera_type", "hfov_deg", "range_m", "unit_price_rm")
        )
        offset_path = _write_temp_csv([{"offset": o} for o in payload.offsets], ("offset",))
        tmp_paths = [building_path, parking_path, poles_path, camera_path, offset_path]

        return run_cctv_pipeline(building_path, parking_path, poles_path, camera_path, offset_path)
    finally:
        for p in tmp_paths:
            Path(p).unlink(missing_ok=True)


@router.post("/genset/route")
def genset_route(payload: GensetRouteRequest) -> dict:
    return route_substations(
        payload.site_lat,
        payload.site_lng,
        [s.model_dump() for s in payload.substations],
        payload.max_road_dist_m,
        payload.graph_buffer_m,
    )


@router.post("/genset/single")
def genset_single(payload: GensetSingleRequest) -> dict:
    """Fetch substations via Overpass and route — no GeoServer dependency."""
    return find_all_power_sources(
        payload.site_lat,
        payload.site_lng,
        max_road_dist_m=payload.max_road_dist_m,
    )


@router.post("/genset/bulk-site-ids")
async def genset_bulk_site_ids(file: UploadFile) -> list[str]:
    """Parses just the site_id column out of an uploaded bulk-routing
    spreadsheet — the same "site_id" header match the legacy app's
    bulk Genset tool used (first sheet, header matched case/
    punctuation-insensitively, falling back to the first column if no
    header matches). The frontend then calls /genset/route once per
    site_id, same as the legacy app's per-site backend route."""
    content = await file.read()
    try:
        df = pd.read_excel(io.BytesIO(content), sheet_name=0) if (file.filename or "").endswith((".xlsx", ".xls")) else pd.read_csv(io.BytesIO(content))
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Could not read spreadsheet: {exc}") from exc

    def normalize(col: str) -> str:
        return re.sub(r"[\s_-]", "", col.lower())

    site_id_col = next((c for c in df.columns if normalize(str(c)) == "siteid"), df.columns[0] if len(df.columns) else None)
    if site_id_col is None:
        return []
    return [str(v).strip() for v in df[site_id_col].dropna().tolist() if str(v).strip()]


@router.post("/genset/bulk-export")
async def genset_bulk_export(file: UploadFile) -> StreamingResponse:
    """
    Streams Server-Sent Events while processing each site, then emits a final
    'done' event containing the Excel workbook as a base64 string so the
    browser can trigger a download without a separate round-trip.

    Event shapes:
      {"type":"start",   "total": N}
      {"type":"progress","i": i, "total": N, "site_id": "...", "status": "found"|"missing"|"error", "sources": K}
      {"type":"done",    "ok": K, "missing": M, "excel_b64": "..."}
      {"type":"error",   "detail": "..."}
    """
    file_bytes = await file.read()
    fname = (file.filename or "").lower()

    async def _stream():
        def _sse(obj: dict) -> str:
            return f"data: {json.dumps(obj)}\n\n"

        # ── Parse spreadsheet ─────────────────────────────────────────────────
        try:
            if fname.endswith((".xlsx", ".xls")):
                raw = pd.read_excel(io.BytesIO(file_bytes), header=None, nrows=3)
                header_row = 0
                for ri in range(min(3, len(raw))):
                    if any("site" in str(v).lower() and "id" in str(v).lower()
                           for v in raw.iloc[ri].tolist()):
                        header_row = ri
                        break
                df = pd.read_excel(io.BytesIO(file_bytes), header=header_row)
            else:
                df = pd.read_csv(io.BytesIO(file_bytes))
        except Exception as exc:
            yield _sse({"type": "error", "detail": f"Could not parse file: {exc}"})
            return

        df.columns = df.columns.str.strip()

        def _find_col(keywords: list[str]) -> str | None:
            for col in df.columns:
                cl = col.lower().replace(" ", "").replace("_", "")
                if any(k in cl for k in keywords):
                    return col
            return None

        site_id_col   = _find_col(["siteid", "site_id"])
        alt_id_col    = _find_col(["altid", "alt_id"])
        name_col      = _find_col(["sitename", "name"])
        region_col    = _find_col(["region"])
        client_col    = _find_col(["client"])
        milestone_col = _find_col(["milestone"])

        if not site_id_col:
            yield _sse({"type": "error", "detail": "No 'SITE ID' column found in the uploaded file"})
            return

        # ── Load coordinates ──────────────────────────────────────────────────
        coord_uri   = parquet_store.parquet_uri("site_coordinates.parquet")
        cellref_uri = parquet_store.parquet_uri("cell_reference.parquet")
        con = get_connection()
        try:
            coord_rows = con.execute(
                f"SELECT UPPER(TRIM(site_id)), latitude, longitude FROM read_parquet('{coord_uri}')"
            ).fetchall()
            try:
                ref_rows = con.execute(f"""
                    SELECT UPPER(TRIM(site_id)), latitude, longitude
                    FROM (
                        SELECT site_id, latitude, longitude,
                               ROW_NUMBER() OVER (PARTITION BY site_id ORDER BY rowid) AS rn
                        FROM read_parquet('{cellref_uri}')
                        WHERE latitude IS NOT NULL AND longitude IS NOT NULL
                    ) t WHERE rn = 1
                """).fetchall()
            except Exception:
                ref_rows = []
        finally:
            con.close()

        db_coords: dict[str, tuple[float, float]] = {}
        for r in ref_rows:
            if r[1] and r[2]:
                db_coords[r[0]] = (float(r[1]), float(r[2]))
        for r in coord_rows:
            if r[1] and r[2]:
                db_coords[r[0]] = (float(r[1]), float(r[2]))

        def _match(raw_id: str) -> tuple[str | None, tuple | None]:
            for candidate in [
                raw_id.strip().upper(),
                re.sub(r'[_ \-].*$', '', raw_id.strip().upper()),
                re.sub(r'\d+$', '', re.sub(r'[_ \-].*$', '', raw_id.strip().upper())),
            ]:
                if candidate in db_coords:
                    return candidate, db_coords[candidate]
            return None, None

        total = len(df)
        yield _sse({"type": "start", "total": total})

        result_rows:  list[dict] = []
        missing_rows: list[dict] = []
        COST_PER_M = 1.0

        for i, (_, row) in enumerate(df.iterrows()):
            raw_id    = str(row.get(site_id_col, "")).strip()
            alt_id    = str(row.get(alt_id_col, "")).strip() if alt_id_col else ""
            site_name = str(row.get(name_col, "")).strip() if name_col else ""
            region    = str(row.get(region_col, "")).strip() if region_col else ""
            client    = str(row.get(client_col, "")).strip() if client_col else ""
            milestone = str(row.get(milestone_col, "")).strip() if milestone_col else ""

            mid, coords = _match(raw_id)
            if not mid and alt_id and alt_id.lower() not in ("nan", ""):
                mid, coords = _match(alt_id)

            if not mid or not coords:
                missing_rows.append({
                    "site_id": raw_id, "alt_id": alt_id if alt_id.lower() != "nan" else "",
                    "site_name": site_name, "region": region, "client": client,
                    "milestone": milestone, "reason": "Site ID not found in coordinates DB",
                })
                yield _sse({"type": "progress", "i": i + 1, "total": total,
                            "site_id": raw_id, "region": region, "status": "missing", "sources": 0})
                continue

            site_lat, site_lon = coords
            try:
                sources = find_all_power_sources(site_lat, site_lon)
            except Exception as exc:
                log.warning("find_all_power_sources failed for %s: %s", raw_id, exc)
                sources = {"substations": [], "electric_poles": [], "error": str(exc)}

            all_sources = sources.get("substations", []) + sources.get("electric_poles", [])

            if not all_sources:
                result_rows.append({
                    "site_id": raw_id, "matched_db_id": mid, "site_name": site_name,
                    "region": region, "client": client, "milestone": milestone,
                    "site_lat": site_lat, "site_lon": site_lon,
                    "power_source_type": "Not Found", "power_source_name": "",
                    "power_source_lat": None, "power_source_lon": None,
                    "operator": "", "voltage": "", "powertype": "",
                    "dist_type": "", "dist_m": None, "dist_km": "", "cost_rm": None,
                })
            else:
                for src in all_sources:
                    dist_m = src.get("dist_m") or 0
                    result_rows.append({
                        "site_id": raw_id, "matched_db_id": mid, "site_name": site_name,
                        "region": region, "client": client, "milestone": milestone,
                        "site_lat": site_lat, "site_lon": site_lon,
                        "power_source_type": src["power_source_type"],
                        "power_source_name": src["name"],
                        "power_source_lat": src["lat"], "power_source_lon": src["lon"],
                        "operator": src.get("operator", ""), "voltage": src.get("voltage", ""),
                        "powertype": src.get("powertype", ""), "dist_type": src.get("dist_type", ""),
                        "dist_m": dist_m, "dist_km": f"{dist_m / 1000:.3f}",
                        "cost_rm": round(dist_m * COST_PER_M, 1),
                    })

            yield _sse({"type": "progress", "i": i + 1, "total": total,
                        "site_id": raw_id, "region": region,
                        "status": "found" if all_sources else "no_sources",
                        "sources": len(all_sources)})
            time.sleep(0.3)

        # ── Build Excel and encode ─────────────────────────────────────────────
        df_results = pd.DataFrame(result_rows)
        df_missing = pd.DataFrame(missing_rows)
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df_results.to_excel(writer, sheet_name="Results", index=False)
            df_missing.to_excel(writer, sheet_name="Missing Sites", index=False)
            for sheet_name, df_sht in [("Results", df_results), ("Missing Sites", df_missing)]:
                ws = writer.sheets[sheet_name]
                for ci, col in enumerate(df_sht.columns, 1):
                    max_w = max(len(str(col)),
                                df_sht[col].astype(str).str.len().max() if not df_sht.empty else 0)
                    ws.column_dimensions[ws.cell(1, ci).column_letter].width = min(max_w + 2, 55)
        buf.seek(0)
        excel_b64 = base64.b64encode(buf.read()).decode()

        yield _sse({
            "type": "done",
            "ok": len(result_rows),
            "missing": len(missing_rows),
            "excel_b64": excel_b64,
        })

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _write_temp_json(data: dict) -> str:
    tmp = tempfile.NamedTemporaryFile(suffix=".geojson", delete=False, mode="w", encoding="utf-8")
    json.dump(data, tmp)
    tmp.close()
    return tmp.name


def _write_temp_csv(rows: list[dict], fieldnames: tuple[str, ...]) -> str:
    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", newline="", encoding="utf-8")
    writer = csv.DictWriter(tmp, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    tmp.close()
    return tmp.name
