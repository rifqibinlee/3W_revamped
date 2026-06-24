"""CCTV site-coverage planning.

Ports `cctv2_pipeline.py` near-verbatim — it was already a clean,
QGIS-free pure-Python pipeline (geopandas/shapely/scipy), nothing here
needed the DuckDB-SQL treatment the ETL pipeline got. The only changes
from the legacy version are organizational (module location) — the
geometry math (hex grid, wedge buffer, azimuth) is unchanged.

Inputs are GeoJSON file paths (building/parking/pole polygons & points)
plus CSV camera/offset spec tables; output is a dict of GeoJSON
FeatureCollections, one per pipeline stage, for the frontend to render.
"""

import csv
import json
import math

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union
from shapely.validation import make_valid


def run_cctv_pipeline(building_path, parking_path, poles_path, camera_csv_path, offset_csv_path):
    """Runs the full CCTV planning pipeline. Returns a dict of
    { layer_name: geojson_dict }."""

    gdf_building = gpd.read_file(building_path)
    gdf_parking = gpd.read_file(parking_path)
    gdf_poles = gpd.read_file(poles_path)

    with open(camera_csv_path) as f:
        camera_rows = list(csv.DictReader(f))
    with open(offset_csv_path) as f:
        offset_rows = list(csv.DictReader(f))

    offsets = [float(r["offset"]) for r in offset_rows]

    # ── Branch A: building candidates (dissolve -> simplify -> fix ->
    # polygons-to-lines -> extract vertices -> dedupe) ──
    dissolved_geom = make_valid(unary_union(gdf_building.geometry))
    gdf_dissolved = gpd.GeoDataFrame(geometry=[dissolved_geom], crs=gdf_building.crs)

    simplified = dissolved_geom.simplify(1, preserve_topology=True)
    fixed = make_valid(simplified)

    def polygon_to_lines(geom):
        lines = []
        if geom.geom_type == "Polygon":
            lines.append(LineString(geom.exterior.coords))
            for interior in geom.interiors:
                lines.append(LineString(interior.coords))
        elif geom.geom_type == "MultiPolygon":
            for poly in geom.geoms:
                lines.extend(polygon_to_lines(poly))
        elif geom.geom_type == "GeometryCollection":
            for g in geom.geoms:
                if g.geom_type in ("Polygon", "MultiPolygon"):
                    lines.extend(polygon_to_lines(g))
        return lines

    building_lines = polygon_to_lines(fixed)

    vertices = set()
    for line in building_lines:
        for coord in line.coords:
            vertices.add((round(coord[0], 8), round(coord[1], 8)))

    candidate_points = [Point(v) for v in vertices]
    gdf_candidate_cctv = gpd.GeoDataFrame(geometry=candidate_points, crs=gdf_building.crs)

    # ── Branch B: merge buildings + parking -> AOI -> hex grid -> centroids ──
    merged_geoms = list(gdf_dissolved.geometry) + list(gdf_parking.geometry)
    gdf_merged = gpd.GeoDataFrame(geometry=merged_geoms, crs=gdf_building.crs)

    surv_geom = make_valid(unary_union(gdf_merged.geometry))
    gdf_surv_area = gpd.GeoDataFrame(geometry=[surv_geom], crs=gdf_building.crs)

    # 0.000269 degrees ~30m; QGIS END_CAP_STYLE=Flat -> shapely cap_style=2,
    # JOIN_STYLE=Miter -> shapely join_style=2.
    aoi_geom = make_valid(
        surv_geom.buffer(0.000269, cap_style=2, join_style=2, mitre_limit=2.0, quad_segs=5)
    )
    gdf_aoi = gpd.GeoDataFrame(geometry=[aoi_geom], crs=gdf_building.crs)

    hspacing = vspacing = 2 * 0.0002695
    hex_grid_polys = _create_hex_grid_qgis(aoi_geom.bounds, hspacing, vspacing)
    gdf_hex_all = gpd.GeoDataFrame(geometry=hex_grid_polys, crs=gdf_building.crs)
    gdf_hex_grid = gpd.clip(gdf_hex_all, gdf_aoi)

    centroids = gdf_hex_grid.geometry.centroid
    gdf_hex_centroids = gpd.GeoDataFrame(geometry=centroids, crs=gdf_building.crs)
    gdf_hex_centroids["xcoord"] = gdf_hex_centroids.geometry.x
    gdf_hex_centroids["ycoord"] = gdf_hex_centroids.geometry.y
    gdf_hex_centroids["HubDist"] = 0.0

    # ── Branch C: poles within parking, then within AOI ──
    gdf_poles_in_parking = gpd.sjoin(gdf_poles, gdf_parking, predicate="within", how="inner").drop(
        columns=["index_right"], errors="ignore"
    )
    gdf_poles_filtered = gdf_poles_in_parking[
        gdf_poles_in_parking.geometry.within(aoi_geom)
    ].reset_index(drop=True)

    # ── Azimuth-to-nearest-hex-centroid for both candidate sets ──
    centroid_coords = np.array([(p.x, p.y) for p in gdf_hex_centroids.geometry])
    tree = cKDTree(centroid_coords) if len(centroid_coords) > 0 else None

    def compute_base_az_and_expand(gdf_candidates, candidate_type):
        if len(gdf_candidates) == 0 or tree is None:
            return gpd.GeoDataFrame(columns=["geometry", "base_az", "azimuth", "type"])

        coords = np.array([(p.x, p.y) for p in gdf_candidates.geometry])
        _, idx = tree.query(coords)

        rows = []
        for i, (_, cand_row) in enumerate(gdf_candidates.iterrows()):
            nearest_hex = centroid_coords[idx[i]]
            base_az = _azimuth_degrees(cand_row.geometry.x, cand_row.geometry.y, nearest_hex[0], nearest_hex[1])
            base_az = (base_az + 360) % 360

            for offset in offsets:
                az = (base_az + offset) % 360
                rows.append({
                    "geometry": cand_row.geometry,
                    "base_az": base_az,
                    "azimuth": az,
                    "offset": offset,
                    "type": candidate_type,
                })

        return gpd.GeoDataFrame(rows, crs=gdf_candidates.crs)

    gdf_building_3az = compute_base_az_and_expand(gdf_candidate_cctv, "building")
    gdf_pole_3az = compute_base_az_and_expand(gdf_poles_filtered, "pole")

    gdf_all_3az = pd.concat([gdf_pole_3az, gdf_building_3az], ignore_index=True)
    if len(gdf_all_3az) > 0:
        gdf_all_3az = gpd.GeoDataFrame(gdf_all_3az, crs=gdf_building.crs)
        # The legacy model hardcodes a single camera type for every
        # candidate position — preserved here, but using the caller's
        # actual first camera type rather than the literal "Type A",
        # since the later merge (on camera_type) silently drops
        # hfov_deg/range_m/unit_price_rm to null for every row whenever
        # the caller's camera CSV doesn't have a row named exactly
        # "Type A" — previously left every position priced at RM0 with
        # no error.
        single_camera_type = camera_rows[0]["camera_type"] if camera_rows else "Type A"
        gdf_all_3az["camera_type"] = single_camera_type
    else:
        gdf_all_3az = gpd.GeoDataFrame(
            columns=["geometry", "base_az", "azimuth", "type", "camera_type"], crs=gdf_building.crs
        )

    cam_df = pd.DataFrame(camera_rows)
    for col in ("hfov_deg", "range_m", "unit_price_rm"):
        if col in cam_df.columns:
            cam_df[col] = pd.to_numeric(cam_df[col], errors="coerce")
    if "camera_type" in cam_df.columns:
        cam_df["camera_type"] = cam_df["camera_type"].str.strip()

    if len(gdf_all_3az) > 0 and len(cam_df) > 0:
        gdf_all_specs = gpd.GeoDataFrame(
            gdf_all_3az.merge(cam_df, on="camera_type", how="left"), crs=gdf_building.crs
        )
    else:
        gdf_all_specs = gdf_all_3az.copy()
        for col in ("hfov_deg", "range_m", "unit_price_rm"):
            if col not in gdf_all_specs.columns:
                gdf_all_specs[col] = 0

    clean_cols = ["geometry", "azimuth", "camera_type", "hfov_deg", "range_m", "unit_price_rm"]
    gdf_cand_clean = gdf_all_specs[[c for c in clean_cols if c in gdf_all_specs.columns]].copy()
    gdf_cand_clean["run_id"] = "cctv_run"

    # Wedge buffer per candidate camera placement.
    wedge_geoms, wedge_attrs = [], []
    for _, row in gdf_all_specs.iterrows():
        az = float(row.get("azimuth", 0))
        hfov = float(row.get("hfov_deg", 90))
        range_m = float(row.get("range_m", 30))
        pt = row.geometry
        wedge_geoms.append(_wedge_buffer(pt.x, pt.y, az, hfov, range_m))
        wedge_attrs.append({
            "camera_type": row.get("camera_type", ""),
            "azimuth": az,
            "hfov_deg": hfov,
            "range_m": range_m,
            "unit_price_rm": row.get("unit_price_rm", 0),
        })

    gdf_wedge = (
        gpd.GeoDataFrame(wedge_attrs, geometry=wedge_geoms, crs=gdf_building.crs)
        if wedge_geoms
        else gpd.GeoDataFrame(columns=["geometry", "camera_type"])
    )

    if len(gdf_all_specs) > 0 and "camera_type" in gdf_all_specs.columns:
        cost_summary = gdf_all_specs.groupby("camera_type").agg(
            count=("azimuth", "size"), unit_price_rm=("unit_price_rm", "min"), total_cost_rm=("unit_price_rm", "sum")
        ).reset_index()
    else:
        cost_summary = pd.DataFrame(columns=["camera_type", "count", "unit_price_rm", "total_cost_rm"])

    def to_geojson(gdf):
        if gdf is None or len(gdf) == 0:
            return {"type": "FeatureCollection", "features": []}
        gdf = gdf.copy()
        for col in gdf.columns:
            if col != "geometry" and gdf[col].dtype == "object":
                gdf[col] = gdf[col].astype(str)
        return json.loads(gdf.to_json())

    def df_to_geojson(df):
        return {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "geometry": None, "properties": {k: _safe_val(v) for k, v in row.items()}}
                for _, row in df.iterrows()
            ],
        }

    return {
        "dissolved_buildings": to_geojson(gdf_dissolved),
        "candidate_cctv": to_geojson(gdf_candidate_cctv),
        "surv_area": to_geojson(gdf_surv_area),
        "aoi": to_geojson(gdf_aoi),
        "hex_grid": to_geojson(gdf_hex_grid),
        "poles": to_geojson(gdf_poles_filtered),
        "cand_cctv_clean": to_geojson(gdf_cand_clean),
        "wedge": to_geojson(gdf_wedge),
        "camera_cost_summary": df_to_geojson(cost_summary),
    }


def _safe_val(v):
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return float(v)
    if pd.isna(v):
        return None
    return v


def _azimuth_degrees(x1, y1, x2, y2):
    """Azimuth in degrees from point1 to point2 (geographic coords),
    matching QGIS's azimuth(): 0=North, clockwise."""
    angle = math.degrees(math.atan2(x2 - x1, y2 - y1))
    return (angle + 360) % 360


def _wedge_buffer(lon, lat, azimuth_deg, hfov_deg, range_m):
    """A wedge/sector polygon. Matches QGIS wedge_buffer() — no cos(lat)
    correction, range treated uniformly in CRS-degree units."""
    range_deg = range_m / 111320.0
    half_fov = hfov_deg / 2.0
    start_az, end_az = azimuth_deg - half_fov, azimuth_deg + half_fov

    points = [(lon, lat)]
    steps = 32
    for i in range(steps + 1):
        az_rad = math.radians(start_az + (end_az - start_az) * i / steps)
        points.append((lon + range_deg * math.sin(az_rad), lat + range_deg * math.cos(az_rad)))
    points.append((lon, lat))

    return Polygon(points)


def _create_hex_grid_qgis(bounds, hspacing, vspacing):
    """Flat-top hexagon grid matching QGIS native:creategrid TYPE=4."""
    minx, miny, maxx, maxy = bounds
    half_w = hspacing / 2.0
    quarter_h = vspacing / 4.0
    row_step = vspacing * 3.0 / 4.0

    polygons = []
    row = 0
    y = miny
    while y <= maxy + vspacing:
        x_offset = half_w if (row % 2 == 1) else 0
        x = minx + x_offset
        while x <= maxx + hspacing:
            polygons.append(Polygon([
                (x, y + vspacing / 2.0),
                (x + half_w, y + quarter_h),
                (x + half_w, y - quarter_h),
                (x, y - vspacing / 2.0),
                (x - half_w, y - quarter_h),
                (x - half_w, y + quarter_h),
                (x, y + vspacing / 2.0),
            ]))
            x += hspacing
        y += row_step
        row += 1

    return polygons
