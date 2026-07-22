"""
Coverage simulation service.

Supported propagation models:
  - hata       : COST-231 Hata (urban macro, 150–2000 MHz)
  - tr38901_uma: 3GPP TR 38.901 Urban Macro (LTE/5G, 0.5–100 GHz)
  - tr38901_rma: 3GPP TR 38.901 Rural Macro
  - spm        : Standard Propagation Model (tunable empirical, Atoll-style)
  - freespace  : Free-space + optional Two-Ray ground reflection
  - sionna     : GPU ray tracing via Sionna RT (if installed)

All non-Sionna models support:
  - Sector antenna pattern (3GPP TR 38.901 horizontal)
  - Building NLOS penalty
  - Monte Carlo log-normal shadow fading (optional, σ = 8 dB)
  - SINR map, RMS delay spread map
"""

from __future__ import annotations

import logging
import math
import random
import time
from dataclasses import dataclass, field
from typing import Literal

log = logging.getLogger(__name__)

_EARTH_R      = 6_371_000.0   # metres
_NOISE_DBM    = -97.0          # -174 + 10*log10(10 MHz) + 7 dB NF
_NLOS_EXTRA_DB = 20.0
_SHADOW_STD_DB = 8.0           # log-normal shadow fading std dev

PropModel = Literal["hata", "tr38901_uma", "tr38901_rma", "spm", "freespace", "sionna"]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class BuildingXY:
    ring: list[tuple[float, float]]
    height_m: float


@dataclass
class SiteTransmitter:
    site_id: str
    lat: float
    lng: float
    antenna_height_m: float
    azimuth_deg: float
    technology: str
    tx_power_dbm: float


@dataclass
class CoveragePoint:
    lat: float
    lng: float
    rsrp_dbm: float
    serving_site_id: str
    nlos: bool = False


# ---------------------------------------------------------------------------
# Coordinate helpers
# ---------------------------------------------------------------------------

def _lat_m_per_deg(ref_lat: float) -> tuple[float, float]:
    m_lat = _EARTH_R * math.pi / 180.0
    m_lng = _EARTH_R * math.cos(math.radians(ref_lat)) * math.pi / 180.0
    return m_lat, m_lng


def _ll_to_xy(lat, lng, origin_lat, origin_lng, m_lat, m_lng):
    return (lng - origin_lng) * m_lng, (lat - origin_lat) * m_lat


def _xy_to_ll(x, y, origin_lat, origin_lng, m_lat, m_lng):
    return origin_lat + y / m_lat, origin_lng + x / m_lng


def _bearing_deg(tx_x: float, tx_y: float, rx_x: float, rx_y: float) -> float:
    dx, dy = rx_x - tx_x, rx_y - tx_y
    return (math.degrees(math.atan2(dx, dy)) + 360) % 360


# ---------------------------------------------------------------------------
# Antenna pattern  (3GPP TR 38.901 horizontal, single sector)
# ---------------------------------------------------------------------------

def _sector_gain_db(
    bearing_to_rx: float,
    tx_azimuth: float,
    h3db: float = 65.0,
    front_back: float = 25.0,
) -> float:
    delta = ((bearing_to_rx - tx_azimuth + 180) % 360) - 180
    return -min(12.0 * (delta / h3db) ** 2, front_back)


# ---------------------------------------------------------------------------
# Propagation models — each returns path_loss_db (positive number)
# ---------------------------------------------------------------------------

def _pl_hata(dist_m: float, freq_mhz: float, h_bs_m: float, h_ue_m: float = 1.5) -> float:
    """COST-231 Hata urban macro path loss (dB)."""
    dist_m  = max(dist_m, 1.0)
    dist_km = dist_m / 1000.0
    h_b     = max(h_bs_m, 1.0)
    a_hms   = 3.2 * (math.log10(11.75 * h_ue_m)) ** 2 - 4.97
    return (46.3 + 33.9 * math.log10(freq_mhz)
            - 13.82 * math.log10(h_b)
            - a_hms
            + (44.9 - 6.55 * math.log10(h_b)) * math.log10(dist_km)
            + 3.0)


def _pl_tr38901_uma(
    dist_m: float,
    freq_mhz: float,
    h_bs_m: float,
    h_ue_m: float = 1.5,
    nlos: bool = False,
) -> float:
    """3GPP TR 38.901 §7.4.1 Urban Macro (UMa) path loss (dB).

    LoS breakpoint distance d_BP' = 4 * h_BS * h_UE * fc / c
    """
    dist_m  = max(dist_m, 10.0)
    fc_hz   = freq_mhz * 1e6
    h_bs    = max(h_bs_m, 10.0)
    h_ue    = max(h_ue_m, 1.5)
    # Effective heights
    h_e     = 1.0   # environment height (assumed 1 m for open UMa)
    h_bs_e  = h_bs - h_e
    h_ue_e  = h_ue - h_e
    d_bp    = 4 * h_bs_e * h_ue_e * fc_hz / 3e8   # breakpoint distance

    if not nlos:
        # LoS
        if dist_m <= d_bp:
            pl = (28.0 + 22 * math.log10(dist_m) + 20 * math.log10(fc_hz / 1e9))
        else:
            pl = (28.0 + 40 * math.log10(dist_m) + 20 * math.log10(fc_hz / 1e9)
                  - 9 * math.log10(d_bp ** 2 + (h_bs - h_ue) ** 2))
    else:
        # NLoS — TR 38.901 eq (7.4-2)
        pl_los  = _pl_tr38901_uma(dist_m, freq_mhz, h_bs_m, h_ue_m, nlos=False)
        pl_nlos = (13.54 + 39.08 * math.log10(dist_m)
                   + 20 * math.log10(fc_hz / 1e9)
                   - 0.6 * (h_ue - 1.5))
        pl = max(pl_los, pl_nlos)

    return pl


def _pl_tr38901_rma(
    dist_m: float,
    freq_mhz: float,
    h_bs_m: float,
    h_ue_m: float = 1.5,
    nlos: bool = False,
    avg_bldg_height_m: float = 5.0,
    avg_street_width_m: float = 20.0,
) -> float:
    """3GPP TR 38.901 §7.4.2 Rural Macro (RMa) path loss (dB)."""
    dist_m  = max(dist_m, 10.0)
    fc_ghz  = freq_mhz / 1e3
    h_bs    = max(h_bs_m, 10.0)
    h_ue    = max(h_ue_m, 1.0)
    h       = avg_bldg_height_m
    W       = avg_street_width_m

    d_bp = 2 * math.pi * h_bs * h_ue * fc_ghz * 1e9 / 3e8

    if not nlos:
        if dist_m <= d_bp:
            pl = (20 * math.log10(40 * math.pi * dist_m * fc_ghz / 3)
                  + min(0.03 * h ** 1.72, 10) * math.log10(dist_m)
                  - min(0.044 * h ** 1.72, 14.77)
                  + 0.002 * math.log10(h) * dist_m)
        else:
            pl0 = (20 * math.log10(40 * math.pi * d_bp * fc_ghz / 3)
                   + min(0.03 * h ** 1.72, 10) * math.log10(d_bp)
                   - min(0.044 * h ** 1.72, 14.77)
                   + 0.002 * math.log10(h) * d_bp)
            pl = pl0 + 40 * math.log10(dist_m / d_bp)
    else:
        pl_los  = _pl_tr38901_rma(dist_m, freq_mhz, h_bs_m, h_ue_m, nlos=False,
                                   avg_bldg_height_m=h, avg_street_width_m=W)
        pl_nlos = (161.04 - 7.1 * math.log10(W) + 7.5 * math.log10(h)
                   - (24.37 - 3.7 * (h / h_bs) ** 2) * math.log10(h_bs)
                   + (43.42 - 3.1 * math.log10(h_bs)) * (math.log10(dist_m) - 3)
                   + 20 * math.log10(fc_ghz)
                   - (3.2 * (math.log10(11.75 * h_ue)) ** 2 - 4.97))
        pl = max(pl_los, pl_nlos)

    return pl


def _pl_spm(
    dist_m: float,
    freq_mhz: float,
    h_bs_m: float,
    h_ue_m: float = 1.5,
    # Tunable coefficients (Atoll defaults for urban)
    K1: float = 23.8,
    K2: float = 44.9,
    K3: float = 5.83,
    K4: float = 0.0,
    K5: float = -6.55,
    K6: float = 0.0,
    Kclutter: float = 3.0,
) -> float:
    """Standard Propagation Model (SPM) — Atoll/Planet style empirical model.

    PL = K1 + K2*log(d) + K3*log(hBS) + K4*L_diffraction
       + K5*log(hBS)*log(d) + K6*hMS + Kclutter
    Diffraction term K4 is 0 here (no terrain).
    """
    dist_m = max(dist_m, 1.0)
    h_bs   = max(h_bs_m, 1.0)
    return (K1
            + K2 * math.log10(dist_m)
            + K3 * math.log10(freq_mhz)
            + K5 * math.log10(h_bs) * math.log10(dist_m)
            - K6 * h_ue_m
            + Kclutter)


def _pl_freespace(
    dist_m: float,
    freq_mhz: float,
    h_bs_m: float = 30.0,
    h_ue_m: float = 1.5,
    two_ray: bool = True,
) -> float:
    """Free-space path loss with optional Two-Ray ground reflection.

    Two-Ray dominates at long range: PL = 40*log10(d) - 20*log10(h_BS*h_UE)
    """
    dist_m = max(dist_m, 1.0)
    fspl   = 20 * math.log10(dist_m) + 20 * math.log10(freq_mhz * 1e6) - 147.55
    if two_ray and dist_m > 4 * h_bs_m * h_ue_m / (3e8 / (freq_mhz * 1e6)):
        # Two-ray crossover
        two_ray_pl = (40 * math.log10(dist_m)
                      - 20 * math.log10(h_bs_m)
                      - 20 * math.log10(h_ue_m))
        return max(fspl, two_ray_pl)
    return fspl


# Map model name → path loss function
_PL_FUNCS: dict[str, object] = {
    "hata":         _pl_hata,
    "tr38901_uma":  _pl_tr38901_uma,
    "tr38901_rma":  _pl_tr38901_rma,
    "spm":          _pl_spm,
    "freespace":    _pl_freespace,
}


# ---------------------------------------------------------------------------
# Building LOS check
# ---------------------------------------------------------------------------

def _segments_intersect(ax, ay, bx, by, cx, cy, dx, dy):
    def _cross(ux, uy, vx, vy): return ux * vy - uy * vx
    abx, aby = bx - ax, by - ay
    d1 = _cross(abx, aby, cx - ax, cy - ay)
    d2 = _cross(abx, aby, dx - ax, dy - ay)
    cdx, cdy = dx - cx, dy - cy
    d3 = _cross(cdx, cdy, ax - cx, ay - cy)
    d4 = _cross(cdx, cdy, bx - cx, by - cy)
    return ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
           ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0))


def _path_blocked(tx_x, tx_y, rx_x, rx_y, buildings):
    for bld in buildings:
        ring = bld.ring
        for i in range(len(ring) - 1):
            if _segments_intersect(tx_x, tx_y, rx_x, rx_y, *ring[i], *ring[i + 1]):
                return True
    return False


# ---------------------------------------------------------------------------
# Image renderer
# ---------------------------------------------------------------------------

def _render_grid(grid, lo, hi, cmap_name="plasma", alpha_lo=0.02):
    """Render a [ny, nx] float grid as a semi-transparent PNG → base64."""
    import base64, io
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    t = np.clip((grid - lo) / (hi - lo), 0.0, 1.0)
    rgba = plt.get_cmap(cmap_name)(t).astype(float)
    rgba[..., 3] = np.where(t < alpha_lo, 0.0, 0.45 + t * 0.50)

    ny, nx = grid.shape
    fig, ax = plt.subplots(figsize=(max(4, nx / 50), max(4, ny / 50)), dpi=100)
    ax.imshow(np.flipud(rgba), origin="upper", aspect="auto", interpolation="bilinear")
    ax.axis("off")
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", pad_inches=0, transparent=True)
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()


def _render_images(rsrp, sinr, delay_spread) -> dict[str, str]:
    return {
        "rsrp":         _render_grid(rsrp,         -140, -70,  "plasma"),
        "sinr":         _render_grid(sinr,          -10,  30,  "RdYlGn"),
        "delay_spread": _render_grid(delay_spread,    0, 500,  "YlOrRd"),
    }


# ---------------------------------------------------------------------------
# Generic grid simulation (all non-Sionna models share this)
# ---------------------------------------------------------------------------

def _generic_simulate(
    sites: list[SiteTransmitter],
    bounds: dict,
    resolution_m: int,
    frequency_mhz: int,
    rx_height_m: float,
    model: str,
    buildings: list[BuildingXY] | None = None,
    monte_carlo: bool = False,
    mc_samples: int = 50,
    shadow_std_db: float = _SHADOW_STD_DB,
) -> tuple[list[CoveragePoint], dict[str, "np.ndarray"]]:
    import numpy as np

    pl_func = _PL_FUNCS[model]
    south, west, north, east = bounds["south"], bounds["west"], bounds["north"], bounds["east"]
    center_lat = (south + north) / 2
    m_lat, m_lng = _lat_m_per_deg(center_lat)
    width_m  = (east - west) * m_lng
    height_m = (north - south) * m_lat
    nx = max(1, int(width_m  / resolution_m))
    ny = max(1, int(height_m / resolution_m))
    n_sites = len(sites)
    use_buildings = bool(buildings)

    tx_xy = [_ll_to_xy(s.lat, s.lng, south, west, m_lat, m_lng) for s in sites]

    # Core: compute deterministic RSRP per TX per cell
    all_rsrp = np.full((n_sites, ny, nx), -200.0)
    nlos_grid = np.zeros((ny, nx), dtype=bool)

    for j in range(ny):
        y = (j + 0.5) / ny * height_m
        for i in range(nx):
            x = (i + 0.5) / nx * width_m
            best_rsrp = -200.0
            best_si   = 0
            best_nlos = False
            for si, s in enumerate(sites):
                tx_x, tx_y = tx_xy[si]
                dist_m = math.hypot(x - tx_x, y - tx_y)
                h_bs   = max(s.antenna_height_m, 1.0)

                nlos = False
                if use_buildings:
                    nlos = _path_blocked(tx_x, tx_y, x, y, buildings)  # type: ignore

                # Path loss — pass nlos where model supports it
                try:
                    pl = pl_func(dist_m, frequency_mhz, h_bs, rx_height_m, nlos=nlos)  # type: ignore
                except TypeError:
                    pl = pl_func(dist_m, frequency_mhz, h_bs, rx_height_m)  # type: ignore

                # Extra building penalty for models that don't handle NLOS internally
                if nlos and model in ("hata", "spm", "freespace"):
                    pl += _NLOS_EXTRA_DB

                # Sector antenna gain
                bearing = _bearing_deg(tx_x, tx_y, x, y)
                pl -= _sector_gain_db(bearing, s.azimuth_deg)

                rsrp = s.tx_power_dbm - pl
                all_rsrp[si, j, i] = rsrp
                if rsrp > best_rsrp:
                    best_rsrp, best_si, best_nlos = rsrp, si, nlos

            if best_nlos:
                nlos_grid[j, i] = True

    # Monte Carlo: add log-normal shadow fading and average
    if monte_carlo and mc_samples > 1:
        rng = np.random.default_rng(42)
        # Draw mc_samples shadow realisations per site per cell
        shadow = rng.normal(0, shadow_std_db, size=(mc_samples, n_sites, ny, nx))
        # rsrp realisations: [samples, n_sites, ny, nx]
        rsrp_mc = all_rsrp[None, :, :, :] + shadow
        # Best-server RSRP per realisation: [samples, ny, nx]
        best_mc = rsrp_mc.max(axis=1)
        # Mean over samples (in linear for accuracy)
        best_mc_w  = 10 ** ((best_mc - 30) / 10)
        mean_rsrp_w = best_mc_w.mean(axis=0)
        rsrp_grid  = 10 * np.log10(np.clip(mean_rsrp_w, 1e-30, None)) + 30
        # For SINR: use mean-power approach
        rsrp_mc_w  = 10 ** ((rsrp_mc - 30) / 10)   # [samples, n_sites, ny, nx]
        mean_per_tx = rsrp_mc_w.mean(axis=0)         # [n_sites, ny, nx]
        noise_w     = 10 ** ((_NOISE_DBM - 30) / 10)
        total_w     = mean_per_tx.sum(axis=0)
        serving_w   = mean_per_tx.max(axis=0)
        best_idx    = mean_per_tx.argmax(axis=0)
    else:
        rsrp_grid = all_rsrp.max(axis=0)
        best_idx  = all_rsrp.argmax(axis=0)
        noise_w   = 10 ** ((_NOISE_DBM - 30) / 10)
        rsrp_w    = 10 ** ((all_rsrp - 30) / 10)
        total_w   = rsrp_w.sum(axis=0)
        serving_w = rsrp_w.max(axis=0)

    interf_w   = total_w - serving_w + noise_w
    sinr_grid  = 10 * np.log10(np.clip(serving_w / interf_w, 1e-10, None))

    # Delay spread: RMS of power-weighted path delays
    tx_xy_arr = np.array(tx_xy)
    xs = np.linspace(0.5 / nx, 1 - 0.5 / nx, nx) * width_m
    ys = np.linspace(0.5 / ny, 1 - 0.5 / ny, ny) * height_m
    gx, gy    = np.meshgrid(xs, ys)
    dists_m   = np.sqrt(
        (gx[None] - tx_xy_arr[:, 0, None, None]) ** 2 +
        (gy[None] - tx_xy_arr[:, 1, None, None]) ** 2
    )
    delays_ns  = dists_m / 0.3
    rsrp_w_det = 10 ** ((all_rsrp - 30) / 10)
    weights    = np.clip(rsrp_w_det, 1e-30, None)
    w_sum      = weights.sum(axis=0) + 1e-30
    mean_del   = (weights * delays_ns).sum(axis=0) / w_sum
    var_del    = (weights * (delays_ns - mean_del[None]) ** 2).sum(axis=0) / w_sum
    ds_grid    = np.sqrt(var_del)

    # Build points list
    points: list[CoveragePoint] = []
    for j in range(ny):
        rx_lat, _ = _xy_to_ll(0, (j + 0.5) / ny * height_m, south, west, m_lat, m_lng)
        for i in range(nx):
            _, rx_lng = _xy_to_ll((i + 0.5) / nx * width_m, 0, south, west, m_lat, m_lng)
            points.append(CoveragePoint(
                lat=rx_lat, lng=rx_lng,
                rsrp_dbm=round(float(rsrp_grid[j, i]), 1),
                serving_site_id=sites[int(best_idx[j, i])].site_id,
                nlos=bool(nlos_grid[j, i]),
            ))

    return points, {"rsrp": rsrp_grid, "sinr": sinr_grid, "delay_spread": ds_grid}


# ---------------------------------------------------------------------------
# Sionna RT simulation
# ---------------------------------------------------------------------------

def _sionna_simulate(
    sites: list[SiteTransmitter],
    bounds: dict,
    resolution_m: int,
    frequency_mhz: int,
    rx_height_m: float,
    buildings: list[BuildingXY] | None = None,
) -> tuple[list[CoveragePoint], dict[str, "np.ndarray"]]:
    import numpy as np
    import sionna.rt as rt  # type: ignore

    south, west, north, east = bounds["south"], bounds["west"], bounds["north"], bounds["east"]
    center_lat = (south + north) / 2
    m_lat, m_lng = _lat_m_per_deg(center_lat)
    origin_lat, origin_lng = south, west
    width_m  = (east - west) * m_lng
    height_m = (north - south) * m_lat

    scene = rt.Scene()
    scene.frequency = frequency_mhz * 1e6

    if buildings:
        for bi, b in enumerate(buildings):
            xs_b = [p[0] for p in b.ring]
            ys_b = [p[1] for p in b.ring]
            cx = (min(xs_b) + max(xs_b)) / 2
            cy = (min(ys_b) + max(ys_b)) / 2
            sx = max(xs_b) - min(xs_b)
            sy = max(ys_b) - min(ys_b)
            if sx < 1 or sy < 1:
                continue
            try:
                scene.add(rt.Box(size=[sx, sy, b.height_m], position=[cx, cy, b.height_m / 2], name=f"bld{bi}"))
            except Exception:
                pass

    tx_array = rt.PlanarArray(num_rows=1, num_cols=1, vertical_spacing=0.5, horizontal_spacing=0.5,
                               pattern="tr38901", polarization="V")
    scene.tx_array = tx_array
    scene.rx_array = rt.PlanarArray(num_rows=1, num_cols=1, vertical_spacing=0.5, horizontal_spacing=0.5,
                                     pattern="dipole", polarization="V")

    tx_power_w = [10 ** ((s.tx_power_dbm - 30) / 10) for s in sites]
    for i, s in enumerate(sites):
        tx_x, tx_y = _ll_to_xy(s.lat, s.lng, origin_lat, origin_lng, m_lat, m_lng)
        yaw = math.radians(90 - s.azimuth_deg)
        scene.add(rt.Transmitter(name=f"tx{i}", position=[tx_x, tx_y, max(s.antenna_height_m, 1.0)],
                                  orientation=[0.0, 0.0, yaw]))

    nx = max(1, int(width_m / resolution_m))
    ny = max(1, int(height_m / resolution_m))

    cm = scene.coverage_map(
        rx_orientation=(0.0, 0.0, 0.0), max_depth=5,
        cm_center=(width_m / 2, height_m / 2, rx_height_m),
        cm_orientation=(0.0, 0.0, 0.0), cm_size=(width_m, height_m),
        cm_cell_size=(float(resolution_m), float(resolution_m)),
        num_samples=int(2e6), los=True, reflection=True, diffraction=True, scattering=True,
    )

    path_gain = cm.path_gain.numpy()
    rsrp_w    = np.array(tx_power_w)[:, None, None] * path_gain
    rsrp_dbm  = 10 * np.log10(np.clip(rsrp_w, 1e-30, None)) + 30
    best_rsrp = rsrp_dbm.max(axis=0)
    best_idx  = rsrp_dbm.argmax(axis=0)

    noise_w   = 10 ** ((_NOISE_DBM - 30) / 10)
    total_w   = rsrp_w.sum(axis=0)
    serving_w = rsrp_w.max(axis=0)
    sinr_grid = 10 * np.log10(np.clip(serving_w / (total_w - serving_w + noise_w), 1e-10, None))

    try:
        ds_grid = cm.rms_delay_spread.numpy() * 1e9
    except Exception:
        ds_grid = np.zeros_like(best_rsrp)

    points: list[CoveragePoint] = []
    for j in range(ny):
        for i in range(nx):
            cx_ = (i + 0.5) / nx * width_m
            cy_ = (j + 0.5) / ny * height_m
            rx_lat, rx_lng = _xy_to_ll(cx_, cy_, origin_lat, origin_lng, m_lat, m_lng)
            points.append(CoveragePoint(lat=rx_lat, lng=rx_lng,
                                         rsrp_dbm=round(float(best_rsrp[j, i]), 1),
                                         serving_site_id=sites[int(best_idx[j, i])].site_id))

    return points, {"rsrp": best_rsrp, "sinr": sinr_grid, "delay_spread": ds_grid}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def simulate(
    sites: list[SiteTransmitter],
    bounds: dict,
    resolution_m: int = 50,
    frequency_mhz: int = 1800,
    tx_power_dbm: float = 43.0,
    rx_height_m: float = 1.5,
    buildings: list[BuildingXY] | None = None,
    model: str = "hata",
    monte_carlo: bool = False,
) -> tuple[list[CoveragePoint], str, dict[str, str]]:
    """
    Returns (points, engine_label, images).
    images = {'rsrp', 'sinr', 'delay_spread'} → base64 PNG strings.
    """
    for s in sites:
        s.tx_power_dbm = tx_power_dbm

    suffix = "+buildings" if buildings else ""
    mc_tag = "+mc" if monte_carlo else ""
    t0 = time.monotonic()

    if model == "sionna":
        try:
            pts, grids = _sionna_simulate(sites, bounds, resolution_m, frequency_mhz, rx_height_m, buildings)
            log.info("Sionna: %d sites → %d pts in %.1fs", len(sites), len(pts), time.monotonic() - t0)
            return pts, f"sionna{suffix}", _render_images(**grids)
        except ImportError:
            log.info("Sionna not installed — falling back to TR 38.901 UMa")
            model = "tr38901_uma"
        except Exception as exc:
            log.warning("Sionna failed (%s) — falling back to TR 38.901 UMa", exc, exc_info=True)
            model = "tr38901_uma"

    if model not in _PL_FUNCS:
        log.warning("Unknown model '%s', defaulting to hata", model)
        model = "hata"

    pts, grids = _generic_simulate(
        sites, bounds, resolution_m, frequency_mhz, rx_height_m,
        model=model, buildings=buildings, monte_carlo=monte_carlo,
    )
    label = f"{model}{mc_tag}{suffix}"
    log.info("%s: %d sites → %d pts in %.1fs", label, len(sites), len(pts), time.monotonic() - t0)
    return pts, label, _render_images(**grids)
