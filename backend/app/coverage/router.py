import time

from fastapi import APIRouter, Depends, HTTPException

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.coverage import buildings as bld_svc
from app.coverage import service as svc
from app.coverage import indoor_service as indoor_svc
from app.coverage.schemas import (
    BuildingFeature,
    CoverageFeature,
    IndoorCoveragePoint,
    IndoorSimulateRequest,
    IndoorSimulateResponse,
    SimulateRequest,
    SimulateResponse,
)
from app.ingestion import parquet_store
from app.analytics.db import get_connection

router = APIRouter(prefix="/coverage", tags=["coverage"])


def _load_sites(bounds, tx_power_dbm: float) -> list[svc.SiteTransmitter]:
    """Query site_coordinates + site_coverage_params within bounds from DuckDB."""
    coord_uri = parquet_store.parquet_uri("site_coordinates.parquet")
    params_uri = parquet_store.parquet_uri("site_coverage_params.parquet")

    con = get_connection()
    try:
        rows = con.execute(f"""
            SELECT
                c.site_id,
                c.latitude,
                c.longitude,
                COALESCE(p.antenna_height, 30.0) AS antenna_height_m,
                COALESCE(p.azimuth, 0.0)         AS azimuth_deg,
                COALESCE(p.technology, '4G')      AS technology
            FROM read_parquet('{coord_uri}') AS c
            LEFT JOIN (
                SELECT site_id,
                       MAX(antenna_height) AS antenna_height,
                       ANY_VALUE(azimuth)  AS azimuth,
                       ANY_VALUE(technology) AS technology
                FROM read_parquet('{params_uri}')
                GROUP BY site_id
            ) AS p ON c.site_id = p.site_id
            WHERE c.latitude  BETWEEN {bounds.south} AND {bounds.north}
              AND c.longitude BETWEEN {bounds.west}  AND {bounds.east}
              AND c.latitude  IS NOT NULL
              AND c.longitude IS NOT NULL
        """).fetchall()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to query site data: {exc}") from exc
    finally:
        con.close()

    return [
        svc.SiteTransmitter(
            site_id=r[0],
            lat=float(r[1]),
            lng=float(r[2]),
            antenna_height_m=float(r[3]) if r[3] else 30.0,
            azimuth_deg=float(r[4]) if r[4] else 0.0,
            technology=str(r[5]) if r[5] else "4G",
            tx_power_dbm=tx_power_dbm,
        )
        for r in rows
    ]


@router.post("/simulate", response_model=SimulateResponse)
def simulate_coverage(
    req: SimulateRequest,
    _user: User = Depends(get_current_user),
) -> SimulateResponse:
    t0 = time.monotonic()

    sites = _load_sites(req.bounds, req.tx_power_dbm)
    if not sites:
        raise HTTPException(
            status_code=422,
            detail="No sites found within the current map bounds. "
                   "Upload site coordinates data first.",
        )

    if len(sites) > 200:
        # Limit to avoid absurdly long simulations at country-wide zoom
        raise HTTPException(
            status_code=422,
            detail=f"{len(sites)} sites in viewport — zoom in so fewer than 200 "
                   "sites are visible before running the simulation.",
        )

    bounds_dict = {
        "south": req.bounds.south,
        "west": req.bounds.west,
        "north": req.bounds.north,
        "east": req.bounds.east,
    }

    # Fetch OSM buildings if requested
    osm_buildings: list[svc.BuildingXY] | None = None
    raw_buildings: list[bld_svc.Building] = []
    if req.include_buildings:
        raw_buildings = bld_svc.fetch(
            req.bounds.south, req.bounds.west,
            req.bounds.north, req.bounds.east,
        )
        osm_buildings = [
            svc.BuildingXY(ring=b.ring_xy, height_m=b.height_m)
            for b in raw_buildings
        ]

    points, engine, images = svc.simulate(
        sites=sites,
        bounds=bounds_dict,
        resolution_m=req.resolution_m,
        frequency_mhz=req.frequency_mhz,
        tx_power_dbm=req.tx_power_dbm,
        buildings=osm_buildings,
        model=req.model,
        monte_carlo=req.monte_carlo,
    )

    return SimulateResponse(
        features=[
            CoverageFeature(
                lat=p.lat,
                lng=p.lng,
                rsrp_dbm=p.rsrp_dbm,
                serving_site_id=p.serving_site_id,
                nlos=p.nlos,
            )
            for p in points
        ],
        buildings=[
            BuildingFeature(ring=b.ring_ll, height_m=b.height_m)
            for b in raw_buildings
        ],
        engine=engine,
        num_sites=len(sites),
        num_buildings=len(raw_buildings),
        simulation_time_s=round(time.monotonic() - t0, 2),
        image_b64=images.get("rsrp"),
        sinr_image_b64=images.get("sinr"),
        delay_spread_image_b64=images.get("delay_spread"),
    )


@router.post("/simulate-indoor", response_model=IndoorSimulateResponse)
def simulate_indoor_coverage(
    req: IndoorSimulateRequest,
    _user: User = Depends(get_current_user),
) -> IndoorSimulateResponse:
    """Sionna RT indoor coverage map from user-drawn walls and TX placements."""
    t0 = time.monotonic()

    if not req.tx_list:
        raise HTTPException(status_code=422, detail="At least one transmitter is required.")
    if req.floor_width_m < 1 or req.floor_height_m < 1:
        raise HTTPException(status_code=422, detail="Floor dimensions must be at least 1 m.")

    walls = [
        indoor_svc.IndoorWall(
            x0=w.x0, y0=w.y0, x1=w.x1, y1=w.y1,
            height_m=w.height_m, material=w.material,
        )
        for w in req.walls
    ]
    tx_list = [
        indoor_svc.IndoorTx(
            x=t.x, y=t.y, height_m=t.height_m,
            power_dbm=t.power_dbm, azimuth_deg=t.azimuth_deg,
        )
        for t in req.tx_list
    ]

    try:
        result = indoor_svc.simulate_indoor(
            walls=walls,
            tx_list=tx_list,
            floor_width_m=req.floor_width_m,
            floor_height_m=req.floor_height_m,
            frequency_mhz=req.frequency_mhz,
            resolution_m=req.resolution_m,
            rx_height_m=req.rx_height_m,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    rsrp  = result["rsrp_grid"]
    sinr  = result["sinr_grid"]
    tx_idx = result["best_tx_idx"]
    nx, ny = result["nx"], result["ny"]
    res   = req.resolution_m

    points = [
        IndoorCoveragePoint(
            x=round((i + 0.5) * res, 2),
            y=round((j + 0.5) * res, 2),
            rsrp_dbm=round(float(rsrp[j, i]), 1),
            sinr_db=round(float(sinr[j, i]), 1),
            serving_tx=int(tx_idx[j, i]),
        )
        for j in range(ny) for i in range(nx)
    ]

    return IndoorSimulateResponse(
        points=points,
        engine="sionna-indoor",
        nx=nx, ny=ny,
        floor_width_m=req.floor_width_m,
        floor_height_m=req.floor_height_m,
        floor_origin_lat=req.floor_origin_lat,
        floor_origin_lng=req.floor_origin_lng,
        simulation_time_s=round(time.monotonic() - t0, 2),
        image_b64=result.get("image_b64"),
        sinr_image_b64=result.get("sinr_image_b64"),
    )
