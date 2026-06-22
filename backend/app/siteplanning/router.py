import csv
import json
import tempfile
from pathlib import Path

from fastapi import APIRouter

from app.siteplanning.cctv import run_cctv_pipeline
from app.siteplanning.genset import route_substations
from app.siteplanning.schemas import CctvRunRequest, GensetRouteRequest

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
